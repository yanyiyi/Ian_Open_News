#!/usr/bin/env python3
"""決策學習迴圈 Stage 1+2：唯讀分析收/不收決策 → 產生系統調整提案。

Stage 1（純統計，不用 AI）：
  a. 正規化不收原因（去「（YYYY-MM-DD，自動批次處理）」後綴）Counter。
  b. keep_keyword 命中仍被拒率（>=80% 且樣本 >=5 → 降級候選）。
  c. 來源拒收率。
  d. under-collected（AI/規則說 skip 但人收了）與 over-collected（說 collect 但被拒）。
  e. 輸出 .cache/taste-retro-report.md 與 .cache/taste-retro-stats.json。

Stage 2（AI 蒸餾，--skip-ai 跳過）：
  把統計與案例交給 claude/codex CLI，產出提案 JSON，驗證 operation.path
  真的存在於目標 JSON 後 append 到 database/system-change-proposals.jsonl。

本 script 對 database/items.jsonl、rejected-items.jsonl、.cache/rss-dismissed.jsonl
一律唯讀；只寫報告、統計、提案與 state 檔。--dry-run 時全不寫。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
CACHE = ROOT / ".cache"

ITEMS_FILE = DATABASE / "items.jsonl"
REJECTED_FILE = DATABASE / "rejected-items.jsonl"
DISMISSED_FILE = CACHE / "rss-dismissed.jsonl"
TASTE_PROFILE_FILE = DATABASE / "taste-profile.json"
TRIAGE_KEYWORDS_FILE = DATABASE / "triage-keywords.json"
DEFAULT_PROPOSALS_FILE = DATABASE / "system-change-proposals.jsonl"
STATE_FILE = CACHE / "taste-retro-state.json"
REPORT_FILE = CACHE / "taste-retro-report.md"
STATS_FILE = CACHE / "taste-retro-stats.json"

FIRST_RUN_SINCE = "2026-06-01"

# 與 scripts/local_web.py rejection_reason_base() 同邏輯（不 import local_web，避免拉起整個 web 模組）。
AUTO_BATCH_SUFFIX_RE = re.compile(r"（\d{4}-\d{2}-\d{2}，自動批次處理）$")

TOP_N = 10
MAX_CASES_PER_PATTERN = 5
MIN_KEYWORD_SAMPLES = 5
KEYWORD_DOWNGRADE_RATE = 0.8
MIN_SOURCE_SAMPLES = 5

VALID_ACTIONS = {"append", "remove", "set"}
VALID_KINDS = {
    "taste-profile-update",
    "triage-keywords-update",
    "tracked-beat-add",
    "needs-code-change",
}
KNOWN_TARGET_FILES = {"taste-profile.json", "triage-keywords.json"}
KIND_DEFAULT_TARGET = {
    "taste-profile-update": "taste-profile.json",
    "tracked-beat-add": "taste-profile.json",
    "triage-keywords-update": "triage-keywords.json",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_status(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    payload = {**payload, "updated_at": now_iso()}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# 正規化與日期
# ---------------------------------------------------------------------------

def normalize_reason(reason: object) -> str:
    """去掉「（YYYY-MM-DD，自動批次處理）」尾綴後回傳原因主體。"""
    text = str(reason or "").strip()
    return AUTO_BATCH_SUFFIX_RE.sub("", text).strip()


def parse_when(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def record_when(record: dict[str, Any]) -> datetime | None:
    decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
    archive = record.get("archive") if isinstance(record.get("archive"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    for value in (
        decision.get("decided_at"),
        record.get("dismissed_at"),
        archive.get("moved_at"),
        editorial.get("generated_at"),
        record.get("captured_at"),
        record.get("published_at"),
    ):
        parsed = parse_when(value)
        if parsed:
            return parsed
    return None


def record_reason(record: dict[str, Any]) -> str:
    decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
    reason = decision.get("reason") or record.get("reason")
    if reason:
        return str(reason).strip()
    notes = str(record.get("notes") or "")
    match = re.search(r"原因：(.+)", notes)
    if match:
        return match.group(1).strip()
    return notes.strip() or "(未填原因)"


def record_key(record: dict[str, Any]) -> str:
    return str(record.get("id") or record.get("url") or record.get("title") or id(record))


def triage_recommendation(record: dict[str, Any]) -> str:
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    return str(triage.get("recommendation") or "")


def editorial_recommendation(record: dict[str, Any]) -> str:
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    return str(editorial.get("recommendation") or "")


def matched_keywords(record: dict[str, Any]) -> list[str]:
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    return [str(keyword).strip() for keyword in triage.get("matched_keywords") or [] if str(keyword).strip()]


def case_of(record: dict[str, Any], decision: str) -> dict[str, str]:
    return {
        "item_id": str(record.get("id") or ""),
        "title": str(record.get("title") or "")[:120],
        "source_name": str(record.get("source_name") or ""),
        "decision": decision,
        "reason": normalize_reason(record_reason(record))[:120],
        "triage_recommendation": triage_recommendation(record),
        "editorial_recommendation": editorial_recommendation(record),
    }


# ---------------------------------------------------------------------------
# Stage 1：純統計
# ---------------------------------------------------------------------------

def load_decisions(since: date, items_file: Path = ITEMS_FILE,
                   rejected_file: Path = REJECTED_FILE,
                   dismissed_file: Path = DISMISSED_FILE) -> tuple[list[dict], list[dict]]:
    """回傳 (kept, rejected)。rejected 合併 rejected-items 與 rss-dismissed，依 id 去重。"""
    def in_range(record: dict[str, Any]) -> bool:
        when = record_when(record)
        return when is None or when.date() >= since

    kept: list[dict] = []
    for record in load_jsonl(items_file):
        decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
        if decision.get("action") == "rejected":
            continue
        if in_range(record):
            kept.append(record)

    rejected_by_key: dict[str, dict] = {}
    for record in load_jsonl(rejected_file):
        if in_range(record):
            record["_decision_source"] = "rejected-items"
            rejected_by_key[record_key(record)] = record
    for record in load_jsonl(dismissed_file):
        if in_range(record):
            key = record_key(record)
            if key not in rejected_by_key:
                record["_decision_source"] = "rss-dismissed"
                rejected_by_key[key] = record
    return kept, list(rejected_by_key.values())


def reason_stats(rejected: list[dict]) -> Counter:
    counter: Counter = Counter()
    for record in rejected:
        counter[normalize_reason(record_reason(record)) or "(未填原因)"] += 1
    return counter


def keep_keyword_stats(kept: list[dict], rejected: list[dict], keyword_config: dict) -> dict[str, dict]:
    """每個 keep_keyword 的命中筆數與被拒率。只看紀錄上留存的 matched_keywords。"""
    keep_set: set[str] = set()
    for track in (keyword_config.get("tracks") or {}).values():
        if isinstance(track, dict):
            keep_set.update(str(keyword).strip() for keyword in track.get("keep_keywords") or [])
    stats: dict[str, dict] = {}
    for records, bucket in ((kept, "kept"), (rejected, "rejected")):
        for record in records:
            for keyword in set(matched_keywords(record)):
                if keep_set and keyword not in keep_set:
                    continue
                entry = stats.setdefault(keyword, {"kept": 0, "rejected": 0, "cases": []})
                entry[bucket] += 1
                if bucket == "rejected" and len(entry["cases"]) < MAX_CASES_PER_PATTERN:
                    entry["cases"].append(case_of(record, "rejected"))
    for keyword, entry in stats.items():
        total = entry["kept"] + entry["rejected"]
        entry["total"] = total
        entry["rejected_rate"] = round(entry["rejected"] / total, 3) if total else 0.0
        entry["downgrade_candidate"] = bool(
            total >= MIN_KEYWORD_SAMPLES and entry["rejected_rate"] >= KEYWORD_DOWNGRADE_RATE
        )
    return stats


def source_stats(kept: list[dict], rejected: list[dict]) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for records, bucket in ((kept, "kept"), (rejected, "rejected")):
        for record in records:
            source = str(record.get("source_name") or "(未知來源)")
            entry = stats.setdefault(source, {"kept": 0, "rejected": 0})
            entry[bucket] += 1
    for entry in stats.values():
        total = entry["kept"] + entry["rejected"]
        entry["total"] = total
        entry["rejected_rate"] = round(entry["rejected"] / total, 3) if total else 0.0
    return stats


def divergence_stats(kept: list[dict], rejected: list[dict]) -> dict[str, Any]:
    under = [record for record in kept if triage_recommendation(record) == "suggest-skip"
             or editorial_recommendation(record) == "suggest-skip"]
    over = [record for record in rejected if triage_recommendation(record) == "suggest-keep"]

    def sort_key(record: dict) -> str:
        when = record_when(record)
        return when.isoformat() if when else ""

    under.sort(key=sort_key, reverse=True)
    over.sort(key=sort_key, reverse=True)
    over_reasons = Counter(normalize_reason(record_reason(record)) or "(未填原因)" for record in over)
    under_sources = Counter(str(record.get("source_name") or "(未知來源)") for record in under)
    return {
        "under_collected": {
            "total": len(under),
            "by_source": dict(under_sources.most_common(TOP_N)),
            "cases": [case_of(record, "collected") for record in under[:TOP_N]],
        },
        "over_collected": {
            "total": len(over),
            "by_reason": dict(over_reasons.most_common(TOP_N)),
            "cases": [case_of(record, "rejected") for record in over[:TOP_N]],
        },
    }


def build_stats(since: date, keyword_config: dict,
                items_file: Path = ITEMS_FILE, rejected_file: Path = REJECTED_FILE,
                dismissed_file: Path = DISMISSED_FILE) -> dict[str, Any]:
    kept, rejected = load_decisions(since, items_file, rejected_file, dismissed_file)
    keywords = keep_keyword_stats(kept, rejected, keyword_config)
    sources = source_stats(kept, rejected)
    return {
        "generated_at": now_iso(),
        "since": since.isoformat(),
        "counts": {"kept": len(kept), "rejected": len(rejected)},
        "rejection_reasons": dict(reason_stats(rejected).most_common()),
        "keep_keyword_rejection": {
            keyword: entry for keyword, entry in sorted(
                keywords.items(), key=lambda pair: (-pair[1]["rejected_rate"], -pair[1]["total"])
            )
        },
        "keyword_downgrade_candidates": [
            {"keyword": keyword, **entry}
            for keyword, entry in sorted(
                keywords.items(), key=lambda pair: (-pair[1]["rejected_rate"], -pair[1]["total"])
            )
            if entry["downgrade_candidate"]
        ],
        "source_rejection": {
            source: entry for source, entry in sorted(
                sources.items(), key=lambda pair: (-pair[1]["rejected_rate"], -pair[1]["total"])
            )
            if entry["total"] >= MIN_SOURCE_SAMPLES
        },
        "divergences": divergence_stats(kept, rejected),
    }


def build_report(stats: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 品味回顧報告（taste retro）")
    lines.append("")
    lines.append(f"- 產生時間：{stats['generated_at']}")
    lines.append(f"- 分析區間：{stats['since']} 起")
    lines.append(f"- 收下 {stats['counts']['kept']} 筆；不收/不要看 {stats['counts']['rejected']} 筆")
    lines.append("")

    lines.append("## 不收原因分佈（已去自動批次日期後綴）")
    lines.append("")
    lines.append("| 原因 | 筆數 |")
    lines.append("| --- | --- |")
    for reason, count in list(stats["rejection_reasons"].items())[:TOP_N]:
        lines.append(f"| {reason} | {count} |")
    lines.append("")

    lines.append(f"## keep_keyword 命中仍被拒（降級門檻：樣本 >= {MIN_KEYWORD_SAMPLES} 且被拒率 >= {KEYWORD_DOWNGRADE_RATE:.0%}）")
    lines.append("")
    lines.append("| 關鍵字 | 命中 | 被拒 | 被拒率 | 降級候選 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for keyword, entry in list(stats["keep_keyword_rejection"].items())[:TOP_N]:
        flag = "是" if entry["downgrade_candidate"] else ""
        lines.append(f"| {keyword} | {entry['total']} | {entry['rejected']} | {entry['rejected_rate']:.0%} | {flag} |")
    lines.append("")

    lines.append(f"## 來源拒收率（樣本 >= {MIN_SOURCE_SAMPLES}）")
    lines.append("")
    lines.append("| 來源 | 筆數 | 被拒 | 拒收率 |")
    lines.append("| --- | --- | --- | --- |")
    for source, entry in list(stats["source_rejection"].items())[:TOP_N]:
        lines.append(f"| {source} | {entry['total']} | {entry['rejected']} | {entry['rejected_rate']:.0%} |")
    lines.append("")

    divergences = stats["divergences"]
    lines.append(f"## under-collected（系統說 skip、人收了）：{divergences['under_collected']['total']} 筆")
    lines.append("")
    for case in divergences["under_collected"]["cases"]:
        lines.append(f"- `{case['item_id']}` {case['title']}（{case['source_name']}）")
    lines.append("")
    lines.append(f"## over-collected（系統說 keep、人不收）：{divergences['over_collected']['total']} 筆")
    lines.append("")
    for reason, count in divergences["over_collected"]["by_reason"].items():
        lines.append(f"- 原因「{reason}」× {count}")
    lines.append("")
    for case in divergences["over_collected"]["cases"]:
        lines.append(f"- `{case['item_id']}` {case['title']}（{case['source_name']}；原因：{case['reason']}）")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# operation 驗證（apply_taste_proposals.py 亦重用）
# ---------------------------------------------------------------------------

def resolve_dot_path(doc: Any, path: str) -> Any:
    node = doc
    for part in str(path).split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            raise KeyError(part)
    return node


def validate_operation(operation: Any, doc: dict[str, Any]) -> tuple[bool, str]:
    """檢查 operation 的 path 真的存在於目標 JSON；append/remove 目標須是 list。"""
    if not isinstance(operation, dict):
        return False, "operation 不是物件"
    action = operation.get("action")
    if action not in VALID_ACTIONS:
        return False, f"action 不合法：{action!r}"
    path = operation.get("path")
    if not path or not isinstance(path, str):
        return False, "缺 path"
    if "value" not in operation:
        return False, "缺 value"
    try:
        node = resolve_dot_path(doc, path)
    except KeyError as exc:
        return False, f"path 不存在於目標 JSON：{path}（缺 {exc.args[0]}）"
    if action in {"append", "remove"} and not isinstance(node, list):
        return False, f"path {path} 不是 list，無法 {action}"
    return True, ""


def proposal_target_file(proposal: dict[str, Any], database_dir: Path = DATABASE) -> Path | None:
    name = Path(str(proposal.get("target_area") or "")).name
    if name not in KNOWN_TARGET_FILES:
        name = KIND_DEFAULT_TARGET.get(str(proposal.get("kind") or ""), "")
    if name not in KNOWN_TARGET_FILES:
        return None
    return database_dir / name


# ---------------------------------------------------------------------------
# Stage 2：AI 蒸餾
# ---------------------------------------------------------------------------

def list_editable_paths(doc: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if not isinstance(doc, dict):
        return paths
    for key, value in doc.items():
        path = f"{prefix}{key}"
        if isinstance(value, list):
            paths.append(f"{path} (list, {len(value)} 項)")
        elif isinstance(value, dict):
            paths.extend(list_editable_paths(value, path + "."))
        else:
            paths.append(f"{path} ({type(value).__name__})")
    return paths


def build_ai_prompt(stats: dict[str, Any], taste_profile: dict, keyword_config: dict) -> str:
    compact_stats = {
        "since": stats["since"],
        "counts": stats["counts"],
        "rejection_reasons_top": dict(list(stats["rejection_reasons"].items())[:TOP_N]),
        "keyword_downgrade_candidates": [
            {
                "keyword": entry["keyword"],
                "total": entry["total"],
                "rejected": entry["rejected"],
                "rejected_rate": entry["rejected_rate"],
                "cases": entry.get("cases", [])[:MAX_CASES_PER_PATTERN],
            }
            for entry in stats["keyword_downgrade_candidates"][:TOP_N]
        ],
        "source_rejection_top": dict(list(stats["source_rejection"].items())[:TOP_N]),
        "under_collected": {
            "total": stats["divergences"]["under_collected"]["total"],
            "cases": stats["divergences"]["under_collected"]["cases"][:MAX_CASES_PER_PATTERN],
        },
        "over_collected": {
            "total": stats["divergences"]["over_collected"]["total"],
            "by_reason": stats["divergences"]["over_collected"]["by_reason"],
            "cases": stats["divergences"]["over_collected"]["cases"][:MAX_CASES_PER_PATTERN],
        },
    }
    profile_paths = "\n".join(f"- {path}" for path in list_editable_paths(taste_profile))
    keyword_paths = "\n".join(f"- {path}" for path in list_editable_paths(keyword_config))
    return f"""你是 Ian Open News 的決策學習分析員。以下是最近一段時間「收下 vs 不收」決策的統計摘要與案例。
請從中蒸餾出可執行的系統調整提案，讓自動分流更貼近使用者實際品味。

## 統計摘要（JSON）
{json.dumps(compact_stats, ensure_ascii=False, indent=2)}

## 可修改的設定檔與 dot path
database/taste-profile.json：
{profile_paths}

database/triage-keywords.json：
{keyword_paths}

## 產出要求
只輸出一個 JSON 物件：{{"proposals": [...]}}，proposals 是陣列，每筆：
{{
  "kind": "taste-profile-update|triage-keywords-update|tracked-beat-add|needs-code-change",
  "target_area": "taste-profile.json 或 triage-keywords.json（needs-code-change 可填程式檔路徑）",
  "operation": {{"path": "<上面列出的 dot path>", "action": "append|remove|set", "value": <任意 JSON>}} 或 null,
  "title": "一句話提案標題（繁體中文）",
  "rationale": "為什麼要改，引用統計數字（繁體中文）",
  "evidence": [{{"item_id": "...", "title": "...", "decision": "collected|rejected", "reason": "..."}}],
  "confidence": "high|medium|low"
}}

規則：
1. operation.path 必須完全取自上面列出的 dot path（去掉括號註記），append/remove 只能對 list。
2. 降級 keep_keyword 用 kind=triage-keywords-update + action=remove；新增追蹤 beat 用 kind=tracked-beat-add append 到 tracked_beats（value 是 {{"beat": "...", "keywords": [...]}}）。
3. 需要改程式邏輯（非設定檔可表達）的洞見，用 kind=needs-code-change、operation=null，target_area 填建議的程式檔。
4. 提案 3 到 8 筆就好，寧缺勿濫；每筆 evidence 至多 {MAX_CASES_PER_PATTERN} 個案例，取自上面統計的案例。
5. 全部用繁體中文（台灣用語）。
"""


def run_ai(prompt: str, engine: str, model: str, timeout: int) -> list[dict[str, Any]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from codex_enrich_reviews import (
        agy_path,
        claude_path,
        cli_env,
        codex_path,
        ollama_model,
        ollama_path,
        parse_cli_json,
    )

    CACHE.mkdir(exist_ok=True)
    (CACHE / "taste-retro-prompt.md").write_text(prompt, encoding="utf-8")
    if engine == "codex":
        output_path = CACHE / "taste-retro-codex-output.json"
        command = [
            codex_path(), "-a", "never", "exec", "--ephemeral",
            "--cd", str(ROOT), "--sandbox", "read-only", "--color", "never",
            "--output-last-message", str(output_path),
        ]
        if model:
            command += ["-m", model]
        command.append("-")
        result = subprocess.run(command, cwd=ROOT, input=prompt, text=True,
                                capture_output=True, timeout=timeout, env=cli_env())
        if result.returncode != 0:
            raise RuntimeError(f"codex exec failed\nSTDOUT:\n{result.stdout[-2000:]}\nSTDERR:\n{result.stderr[-2000:]}")
        raw = output_path.read_text(encoding="utf-8")
    elif engine == "gemini":
        command = [agy_path(), "--print", prompt]
        if model:
            command += ["--model", model]
        result = subprocess.run(command, cwd=ROOT, text=True,
                                capture_output=True, timeout=timeout, env=cli_env())
        if result.returncode != 0:
            raise RuntimeError(f"agy print failed\nSTDERR:\n{result.stderr[-2000:]}")
        (CACHE / "taste-retro-gemini-output.json").write_text(result.stdout, encoding="utf-8")
        raw = result.stdout
    elif engine.startswith("ollama"):
        resolved_model = model or ollama_model(engine)
        command = [ollama_path(), "run", resolved_model, "--format", "json", "--nowordwrap", "--hidethinking"]
        result = subprocess.run(command, cwd=ROOT, input=prompt, text=True,
                                capture_output=True, timeout=timeout, env=cli_env())
        if result.returncode != 0:
            raise RuntimeError(f"ollama run failed（model: {resolved_model}）\nSTDERR:\n{result.stderr[-2000:]}")
        (CACHE / "taste-retro-ollama-output.json").write_text(result.stdout, encoding="utf-8")
        raw = result.stdout
    else:
        command = [claude_path(), "-p", prompt, "--output-format", "json"]
        if model:
            command += ["--model", model]
        result = subprocess.run(command, cwd=ROOT, text=True,
                                capture_output=True, timeout=timeout, env=cli_env())
        if result.returncode != 0:
            raise RuntimeError(f"claude print failed\nSTDOUT:\n{result.stdout[-2000:]}\nSTDERR:\n{result.stderr[-2000:]}")
        (CACHE / "taste-retro-claude-output.json").write_text(result.stdout, encoding="utf-8")
        raw = result.stdout

    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict) or "proposals" not in payload:
        payload = parse_cli_json(raw)
    proposals = payload.get("proposals") if isinstance(payload, dict) else None
    if not isinstance(proposals, list):
        raise RuntimeError("AI 輸出缺少 proposals 陣列")
    return [proposal for proposal in proposals if isinstance(proposal, dict)]


def sanitize_evidence(raw: Any) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return evidence
    for entry in raw[:MAX_CASES_PER_PATTERN]:
        if not isinstance(entry, dict):
            continue
        evidence.append({
            "item_id": str(entry.get("item_id") or ""),
            "title": str(entry.get("title") or "")[:160],
            "decision": str(entry.get("decision") or ""),
            "reason": str(entry.get("reason") or "")[:160],
        })
    return evidence


def finalize_proposals(raw_proposals: list[dict[str, Any]], engine: str,
                       source_report: str, database_dir: Path = DATABASE) -> list[dict[str, Any]]:
    """驗證 AI 提案、補系統欄位。operation 不合法者降為 needs-code-change。"""
    proposed_at = now_iso()
    docs_cache: dict[Path, dict] = {}
    finalized: list[dict[str, Any]] = []
    for raw in raw_proposals:
        kind = str(raw.get("kind") or "")
        if kind not in VALID_KINDS:
            kind = "needs-code-change"
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        proposal: dict[str, Any] = {
            "kind": kind,
            "target_area": str(raw.get("target_area") or ""),
            "operation": raw.get("operation") if isinstance(raw.get("operation"), dict) else None,
            "title": title,
            "rationale": str(raw.get("rationale") or "").strip(),
            "evidence": sanitize_evidence(raw.get("evidence")),
            "confidence": str(raw.get("confidence") or "medium"),
            "notes": "",
            "proposed_at": proposed_at,
            "source_engine": engine,
            "source_report": source_report,
            "status": "proposed",
        }
        if proposal["kind"] != "needs-code-change":
            target = proposal_target_file(proposal, database_dir)
            invalid_reason = ""
            if target is None:
                invalid_reason = f"target_area 無法對應設定檔：{proposal['target_area']!r}"
            else:
                if target not in docs_cache:
                    docs_cache[target] = load_json(target)
                ok, why = validate_operation(proposal["operation"], docs_cache[target])
                if not ok:
                    invalid_reason = why
            if invalid_reason:
                proposal["notes"] = f"operation 驗證未過（{invalid_reason}），降為 needs-code-change。"
                proposal["kind"] = "needs-code-change"
                proposal["operation"] = None
        proposal["id"] = "prop-" + hashlib.sha1(f"{title}|{proposed_at}".encode("utf-8")).hexdigest()[:8]
        finalized.append(proposal)
    return finalized


def append_proposals(proposals: list[dict[str, Any]], proposals_file: Path) -> tuple[int, int]:
    """append 新提案；與既有 status=proposed 同 title 者跳過。回傳 (新增, 跳過)。"""
    existing = load_jsonl(proposals_file)
    existing_titles = {
        str(record.get("title") or "").strip()
        for record in existing
        if record.get("status") == "proposed"
    }
    added = 0
    skipped = 0
    proposals_file.parent.mkdir(parents=True, exist_ok=True)
    with proposals_file.open("a", encoding="utf-8") as handle:
        for proposal in proposals:
            if proposal["title"] in existing_titles:
                skipped += 1
                continue
            handle.write(json.dumps(proposal, ensure_ascii=False, sort_keys=True) + "\n")
            existing_titles.add(proposal["title"])
            added += 1
    return added, skipped


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def resolve_since(arg_since: str | None) -> date:
    if arg_since:
        return date.fromisoformat(arg_since)
    state = load_json(STATE_FILE)
    last_run = parse_when(state.get("last_run_at"))
    if last_run:
        return last_run.date()
    return date.fromisoformat(FIRST_RUN_SINCE)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="決策學習迴圈：統計收/不收決策並產生系統調整提案（唯讀分析）。")
    parser.add_argument("--since", help="只分析這天（YYYY-MM-DD）之後的決策；預設讀 state 檔 last_run_at，首跑 %s。" % FIRST_RUN_SINCE)
    parser.add_argument(
        "--engine",
        choices=["claude", "codex", "gemini", "ollama-gemma4", "ollama-twinkle"],
        default="claude",
        help="全部引擎開放自選；本機 ollama 小模型消化大量統計可能失敗，風險自負",
    )
    parser.add_argument("--model", default="", help="覆寫引擎預設模型（選用）。")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="全不寫檔，只印報告。")
    parser.add_argument("--skip-ai", action="store_true", help="只跑 Stage 1 統計，不呼叫 AI。")
    parser.add_argument("--status-file", type=Path, default=None)
    parser.add_argument("--proposals-file", type=Path, default=DEFAULT_PROPOSALS_FILE)
    args = parser.parse_args(argv)

    status_file = None if args.dry_run else args.status_file
    since = resolve_since(args.since)
    write_status(status_file, {"state": "running", "stage": "stage1", "since": since.isoformat()})

    keyword_config = load_json(TRIAGE_KEYWORDS_FILE)
    taste_profile = load_json(TASTE_PROFILE_FILE)
    stats = build_stats(since, keyword_config)
    report = build_report(stats)

    if args.dry_run:
        print(report)
    else:
        CACHE.mkdir(exist_ok=True)
        REPORT_FILE.write_text(report, encoding="utf-8")
        STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Stage 1 完成：報告 {REPORT_FILE.relative_to(ROOT)}、統計 {STATS_FILE.relative_to(ROOT)}")
        print(f"  收下 {stats['counts']['kept']} 筆 / 不收 {stats['counts']['rejected']} 筆；"
              f"降級候選 {len(stats['keyword_downgrade_candidates'])} 個；"
              f"under-collected {stats['divergences']['under_collected']['total']} 筆、"
              f"over-collected {stats['divergences']['over_collected']['total']} 筆")

    added = 0
    skipped = 0
    if not args.skip_ai:
        write_status(status_file, {"state": "running", "stage": "stage2-ai", "engine": args.engine})
        source_report = f"retro-{date.today().isoformat()}"
        try:
            raw_proposals = run_ai(build_ai_prompt(stats, taste_profile, keyword_config),
                                   args.engine, args.model, args.timeout)
        except Exception as exc:  # noqa: BLE001 — 回報 UI 後照樣結束
            write_status(status_file, {"state": "error", "stage": "stage2-ai", "error": str(exc)[:800]})
            print(f"Stage 2 AI 失敗：{exc}", file=sys.stderr)
            return 1
        proposals = finalize_proposals(raw_proposals, args.engine, source_report)
        if args.dry_run:
            print(f"[dry-run] AI 產出 {len(proposals)} 筆提案（不寫入）：")
            for proposal in proposals:
                print(f"  - [{proposal['kind']}] {proposal['title']}")
        else:
            added, skipped = append_proposals(proposals, args.proposals_file)
            print(f"Stage 2 完成：新增 {added} 筆提案到 {args.proposals_file}（同標題跳過 {skipped} 筆）。")

    if not args.dry_run:
        state = load_json(STATE_FILE)
        state["last_run_at"] = now_iso()
        state["last_since"] = since.isoformat()
        CACHE.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    write_status(status_file, {
        "state": "done",
        "since": since.isoformat(),
        "kept": stats["counts"]["kept"],
        "rejected": stats["counts"]["rejected"],
        "proposals_added": added,
        "proposals_skipped": skipped,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
