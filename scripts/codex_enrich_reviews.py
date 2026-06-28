#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
REPORT = ROOT / ".cache" / "codex-review-report.md"
TASTE_PROFILE = ROOT / "database" / "taste-profile.json"

READER_STATUSES = {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}
READER_ACTIONS = {"accepted-for-editing", "direct-pr-small-news", "revisit-with-personal-notes"}
CURRENT_READING_PRIORITY_DAYS = 1
DEFAULT_OLLAMA_MODEL = "TwinkleAI/gemma-3-4B-T1-it"
# 隨機（--provider random）時每筆獨立抽引擎的加權比例。
PROVIDER_WEIGHTS = {"codex": 35, "claude": 35, "gemini": 15, "ollama": 15}
AI_PROVIDERS = {
    "codex": {
        "label": "Codex",
        "review_key": "codex_review",
        "generated_key": "codex_generated_at",
        "generator": "codex-cli",
    },
    "claude": {
        "label": "Claude Code",
        "review_key": "claude_review",
        "generated_key": "claude_generated_at",
        "generator": "claude-code-cli",
    },
    "gemini": {
        "label": "Gemini",
        "review_key": "gemini_review",
        "generated_key": "gemini_generated_at",
        "generator": "agy-cli",
    },
    "ollama": {
        "label": "Ollama CLI",
        "review_key": "ollama_review",
        "generated_key": "ollama_generated_at",
        "generator": "ollama-cli",
    },
}


def clean_text(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value)
    text = " ".join(text.replace("\r", "\n").split()) if "\n" not in text else text
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    text = "\n".join(line for line in text.split("\n") if line).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        record["_line"] = line_number
        records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def codex_path() -> str:
    candidate = shutil.which("codex")
    if candidate:
        return candidate
    for path in [str(Path.home() / ".local" / "bin" / "codex"), "/opt/homebrew/bin/codex", "/usr/local/bin/codex"]:
        if Path(path).exists():
            return path
    raise RuntimeError("找不到 codex CLI，請先確認 /opt/homebrew/bin/codex 是否可用。")


def claude_path() -> str:
    candidate = shutil.which("claude")
    if candidate:
        return candidate
    for path in [str(Path.home() / ".local" / "bin" / "claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"]:
        if Path(path).exists():
            return path
    raise RuntimeError("找不到 claude CLI，請先確認 /opt/homebrew/bin/claude 是否可用。")


def agy_path() -> str:
    candidate = shutil.which("agy")
    if candidate:
        return candidate
    for path in [str(Path.home() / ".local" / "bin" / "agy"), "/opt/homebrew/bin/agy", "/usr/local/bin/agy"]:
        if Path(path).exists():
            return path
    raise RuntimeError("找不到 agy CLI，請先確認 /opt/homebrew/bin/agy 是否可用。")


def ollama_path() -> str:
    candidate = shutil.which("ollama")
    if candidate:
        return candidate
    for path in [str(Path.home() / ".local" / "bin" / "ollama"), "/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"]:
        if Path(path).exists():
            return path
    raise RuntimeError("找不到 ollama CLI，請先安裝 Ollama，並設定 OLLAMA_MODEL 或 OLLAMA_CLI_MODEL。")


def ollama_model() -> str:
    model = (os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_CLI_MODEL") or DEFAULT_OLLAMA_MODEL).strip()
    return model or DEFAULT_OLLAMA_MODEL


def cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = (
        f"{Path.home() / '.local' / 'bin'}:"
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
        + env.get("PATH", "")
    )
    return env


def provider_meta(provider: str) -> dict[str, str]:
    return AI_PROVIDERS.get(provider, AI_PROVIDERS["codex"])


def load_json_from_text(text: str) -> Any:
    raw = text.strip()
    if not raw:
        raise RuntimeError("model output is empty")
    candidates = [raw]
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())
    object_match = re.search(r"\{.*\}", raw, flags=re.S)
    if object_match:
        candidates.append(object_match.group(0).strip())
    last_line = next((line.strip() for line in reversed(raw.splitlines()) if line.strip()), "")
    if last_line and last_line not in candidates:
        candidates.append(last_line)
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("model output missing valid JSON payload")


def parse_cli_json(raw: str) -> dict[str, Any]:
    payload = load_json_from_text(raw)
    if isinstance(payload, dict) and "reviews" in payload:
        return payload
    if isinstance(payload, dict) and "result" in payload:
        result = payload["result"]
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            result_payload = load_json_from_text(result)
            if isinstance(result_payload, dict):
                return result_payload
    if isinstance(payload, dict) and "message" in payload and isinstance(payload["message"], dict):
        return payload["message"]
    raise RuntimeError("model output missing structured payload")


def available_providers() -> list[str]:
    available: list[str] = []
    for provider, finder in [("codex", codex_path), ("claude", claude_path), ("gemini", agy_path), ("ollama", ollama_path)]:
        try:
            finder()
        except RuntimeError:
            continue
        available.append(provider)
    return available


def weighted_choice(providers: list[str]) -> str:
    """在可用引擎中依 PROVIDER_WEIGHTS 加權抽一個；權重全為 0 時退回等機率。"""
    weights = [PROVIDER_WEIGHTS.get(provider, 0) for provider in providers]
    if sum(weights) <= 0:
        return random.choice(providers)
    return random.choices(providers, weights=weights, k=1)[0]


def has_provider_review(record: dict[str, Any], provider: str) -> bool:
    editorial = record.get("editorial_triage")
    if not isinstance(editorial, dict):
        return False
    return isinstance(editorial.get(provider_meta(provider)["review_key"]), dict)


def has_any_review(record: dict[str, Any]) -> bool:
    editorial = record.get("editorial_triage")
    if not isinstance(editorial, dict):
        return False
    return any(isinstance(editorial.get(provider_meta(name)["review_key"]), dict) for name in AI_PROVIDERS)


def local_decision_action(record: dict[str, Any]) -> str:
    decision = record.get("local_decision")
    if not isinstance(decision, dict):
        return ""
    return str(decision.get("action") or "")


def parse_datetime(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def reader_flags(record: dict[str, Any]) -> dict[str, Any]:
    flags = record.get("reader_flags")
    return flags if isinstance(flags, dict) else {}


def current_reading_rank(record: dict[str, Any]) -> int:
    flags = reader_flags(record)
    active = bool(flags.get("current_reading") or flags.get("share_intent"))
    if not active:
        return 2
    started = parse_datetime(flags.get("started_at") or flags.get("flagged_at"))
    if started and (datetime.now(timezone.utc) - started).days >= CURRENT_READING_PRIORITY_DAYS:
        return 0
    return 1


def target_recency(record: dict[str, Any]) -> str:
    flags = reader_flags(record)
    decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
    return clean_text(
        flags.get("updated_at")
        or flags.get("started_at")
        or decision.get("decided_at")
        or record.get("captured_at")
        or record.get("published_at")
    )


def in_item_scope(record: dict[str, Any], tracks: set[str], statuses: set[str], workflow_scope: bool) -> bool:
    if tracks and record.get("track") not in tracks:
        return False
    if workflow_scope:
        status = record.get("status")
        action = local_decision_action(record)
        return status == "inbox" or status in READER_STATUSES or action in READER_ACTIONS
    return record.get("status") in statuses


def in_candidate_scope(record: dict[str, Any], tracks: set[str]) -> bool:
    if tracks and record.get("track") not in tracks:
        return False
    return record.get("candidate_status", "pending") == "pending"


def source_material(record: dict[str, Any]) -> tuple[str, str, bool]:
    reading = record.get("reading_metadata")
    reading = reading if isinstance(reading, dict) else {}
    enrichment = record.get("article_enrichment")
    enrichment = enrichment if isinstance(enrichment, dict) else {}

    article_text = clean_text(reading.get("article_text"), 5000)
    if article_text:
        return article_text, "主文全文", False

    sentences = enrichment.get("summary_sentences")
    if isinstance(sentences, list):
        text = clean_text("\n".join(str(sentence) for sentence in sentences if sentence), 2200)
        if text:
            return text, "已抽取正文摘要", True

    summary = clean_text(record.get("summary"), 2200)
    description = clean_text(reading.get("description"), 1200)
    if summary and description and description not in summary:
        return f"{summary}\n{description}", "RSS 摘要與頁面描述", True
    if summary:
        return summary, "RSS 摘要", True
    if description:
        return description, "頁面描述", True

    title = clean_text(record.get("title"), 500)
    return title, "只有標題", True


def review_input(record: dict[str, Any]) -> dict[str, Any]:
    text, basis, needs_fulltext = source_material(record)
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    return {
        "id": record.get("id"),
        "track": record.get("track"),
        "status": record.get("status"),
        "title": clean_text(record.get("title"), 360),
        "url": record.get("url", ""),
        "source_name": record.get("source_name", ""),
        "published_at": record.get("published_at", ""),
        "tags": record.get("tags", [])[:12] if isinstance(record.get("tags"), list) else [],
        "local_rule_recommendation": triage.get("recommendation", ""),
        "matched_keywords": triage.get("matched_keywords", []),
        "local_content_kind": editorial.get("content_kind", ""),
        "source_basis": basis,
        "needs_fulltext": needs_fulltext,
        "source_text": text,
    }


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviews"],
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "zh_title",
                        "one_line_recommendation",
                        "reasons",
                        "summary",
                        "recommendation",
                        "content_kind",
                        "confidence",
                        "needs_fulltext",
                        "note",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "zh_title": {"type": "string"},
                        "one_line_recommendation": {"type": "string"},
                        "reasons": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "string"},
                        },
                        "summary": {"type": "string"},
                        "recommendation": {
                            "type": "string",
                            "enum": ["recommend-collect", "recommend-review", "recommend-skip"],
                        },
                        "content_kind": {
                            "type": "string",
                            "enum": ["featured-article", "small-news", "needs-review"],
                        },
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "needs_fulltext": {"type": "boolean"},
                        "note": {"type": "string"},
                    },
                },
            }
        },
    }


def taste_profile_block() -> str:
    """讀 taste-profile.json，組成可注入 prompt 的「使用者品味」區塊。缺檔回空字串。"""
    if not TASTE_PROFILE.exists():
        return ""
    try:
        profile = json.loads(TASTE_PROFILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    if not isinstance(profile, dict):
        return ""
    lines: list[str] = []
    g = profile.get("global") or {}
    if g.get("emphasize"):
        lines.append("優先重視：" + "、".join(g["emphasize"]))
    if g.get("de_emphasize"):
        lines.append("要警惕/淡化：" + "、".join(g["de_emphasize"]))
    if g.get("taiwan_context_required"):
        lines.append("台灣切角為必要條件")
    for track, meta in (profile.get("tracks") or {}).items():
        prio = (meta or {}).get("priority_themes") or []
        avoid = (meta or {}).get("avoid_themes") or []
        if prio:
            lines.append(f"[{track}] 偏好主題：" + "、".join(prio))
        if avoid:
            lines.append(f"[{track}] 避開主題：" + "、".join(avoid))
    for sig in (profile.get("learned_signals") or []):
        if isinstance(sig, dict) and sig.get("signal"):
            lines.append("已從過去決策學到：" + sig["signal"])
    if not lines:
        return ""
    body = "\n".join(f"- {line}" for line in lines)
    return f"""
## 使用者品味（請優先參考，這是 Ian 的個人判斷偏好）
{body}

請在判斷 recommendation / confidence / content_kind 時把上述品味納入考量；命中偏好主題、有台灣切角的，傾向 recommend-collect 或 recommend-review，不要輕易 skip。
"""


def build_prompt(batch: list[dict[str, Any]], provider: str = "codex") -> str:
    label = provider_meta(provider)["label"]
    data = json.dumps({"items": batch}, ensure_ascii=False, indent=2)
    taste = taste_profile_block()
    return f"""你是 Ian Open News 的編輯助理，請為下列 RSS/知識項目補上 {label} 版閱讀建議。
{taste}

請只根據每筆提供的 source_text 判斷，不要上網，不要補不存在的事實。
若 source_basis 是「只有標題」或 source_text 太短，請明確降低 confidence，needs_fulltext 設為 true，摘要只做保守判斷。

每筆請產生：
- zh_title：如果原標題是英文，翻成自然繁體中文；如果已是中文，可微調成清楚標題。
- one_line_recommendation：用「給 Ian 的一句話推薦」語氣，說清楚值不值得先看，以及最有價值的角度。
- reasons：三個「看它的理由」，要是編輯判斷，不要只是重複關鍵字。
- summary：繁體中文摘要，盡量像人讀完後重寫，避免「這是一篇英文資料，可能和...有關」這種模板句。
- recommendation：recommend-collect / recommend-review / recommend-skip。
- content_kind：featured-article 表示值得跑 skill；small-news 表示純新聞或小消息可直接查核送 PR；needs-review 表示需要人工判斷。
- note：一句話說明判斷依據或限制。

回覆必須符合 JSON schema，不要輸出 Markdown。

資料：
{data}
"""


def run_codex(batch: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema_path = cache / "codex-review.schema.json"
    output_path = cache / "codex-review-output.json"
    prompt_path = cache / "codex-review-prompt.json"
    schema_path.write_text(json.dumps(output_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = build_prompt(batch, "codex")
    prompt_path.write_text(prompt, encoding="utf-8")

    command = [
        codex_path(),
        "-a",
        "never",
        "exec",
        "--ephemeral",
        "--cd",
        str(ROOT),
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "-",
    ]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "codex exec failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    raw = output_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("Codex output missing reviews array")
    return reviews


def run_claude(batch: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(batch, "claude")
    # Claude CLI（2.x）沒有 --json-schema/--tools 這些旗標；用有效旗標並把 schema 寫進 prompt，
    # 再從回傳 JSON 的 result 欄位解析（與 editor_task.py / run_gemini 一致）。
    prompt += f"\n\n請務必只輸出 JSON 物件，且完全符合以下 JSON Schema，不要任何額外說明或 markdown 包裝：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    (cache / "claude-review-prompt.json").write_text(prompt, encoding="utf-8")
    command = [
        claude_path(),
        "-p",
        prompt,
        "--output-format",
        "json",
    ]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "claude print failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    (cache / "claude-review-output.json").write_text(result.stdout, encoding="utf-8")
    payload = parse_cli_json(result.stdout)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("Claude output missing reviews array")
    return reviews


def run_gemini(batch: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(batch, "gemini")
    prompt += f"\n\n請務必輸出 JSON 格式，並完全符合以下 JSON Schema：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    (cache / "gemini-review-prompt.json").write_text(prompt, encoding="utf-8")
    command = [
        agy_path(),
        "--print",
        prompt,
    ]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "agy print failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    (cache / "gemini-review-output.json").write_text(result.stdout, encoding="utf-8")
    payload = parse_cli_json(result.stdout)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("Gemini output missing reviews array")
    return reviews


def run_ollama(batch: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(batch, "ollama")
    prompt += f"\n\n請務必只輸出 JSON 物件，且完全符合以下 JSON Schema，不要任何額外說明或 markdown 包裝：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    (cache / "ollama-review-prompt.json").write_text(prompt, encoding="utf-8")
    model = ollama_model()
    command = [
        ollama_path(),
        "run",
        model,
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=cli_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ollama run failed（model: {model}）\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    (cache / "ollama-review-output.json").write_text(result.stdout, encoding="utf-8")
    payload = parse_cli_json(result.stdout)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("Ollama output missing reviews array")
    return reviews


def run_provider(batch: list[dict[str, Any]], args: argparse.Namespace, provider: str) -> list[dict[str, Any]]:
    if provider == "claude":
        return run_claude(batch, args)
    if provider == "gemini":
        return run_gemini(batch, args)
    if provider == "ollama":
        return run_ollama(batch, args)
    return run_codex(batch, args)


def formatted_summary(review: dict[str, Any]) -> str:
    reasons = review.get("reasons") if isinstance(review.get("reasons"), list) else []
    reasons = [clean_text(reason) for reason in reasons[:3]]
    while len(reasons) < 3:
        reasons.append("來源資訊不足，建議補抓全文後再判斷。")
    return "\n".join(
        [
            f"中文標題：{clean_text(review.get('zh_title'))}",
            "",
            f"給 Ian 的一句話推薦：{clean_text(review.get('one_line_recommendation'))}",
            "",
            "三個看它的理由",
            f"1. {reasons[0]}",
            f"2. {reasons[1]}",
            f"3. {reasons[2]}",
            "",
            "摘要",
            clean_text(review.get("summary")),
        ]
    ).strip()


def apply_reviews(records: list[dict[str, Any]], reviews: list[dict[str, Any]], provider: str) -> int:
    meta = provider_meta(provider)
    by_id = {str(review.get("id")): review for review in reviews if review.get("id")}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = 0
    for record in records:
        record_id = str(record.get("id") or "")
        review = by_id.get(record_id)
        if not review:
            continue
        editorial = record.get("editorial_triage")
        if not isinstance(editorial, dict):
            editorial = {}
        reasons = review.get("reasons") if isinstance(review.get("reasons"), list) else []
        reasons = [clean_text(reason) for reason in reasons[:3]]
        while len(reasons) < 3:
            reasons.append("來源資訊不足，建議補抓全文後再判斷。")
        provider_review = {
            "source": meta["label"],
            "generator": meta["generator"],
            "generated_at": generated_at,
            "version": 1,
            "zh_title": clean_text(review.get("zh_title"), 300),
            "one_line_recommendation": clean_text(review.get("one_line_recommendation"), 500),
            "reasons": reasons,
            "summary": clean_text(review.get("summary"), 1600),
            "recommendation": review.get("recommendation"),
            "content_kind": review.get("content_kind"),
            "confidence": review.get("confidence"),
            "needs_fulltext": bool(review.get("needs_fulltext")),
            "note": clean_text(review.get("note"), 500),
        }
        editorial[meta["review_key"]] = provider_review
        has_codex = isinstance(editorial.get("codex_review"), dict)
        if provider == "codex" or not has_codex:
            editorial["zh_title"] = provider_review["zh_title"] or clean_text(record.get("title"), 300)
            editorial["zh_summary"] = formatted_summary(review)
            editorial["summary_reason"] = f"已由 {meta['label']} 依目前可讀資料補閱讀建議與摘要。"
        editorial[meta["generated_key"]] = generated_at
        record["editorial_triage"] = editorial
        changed += 1
    return changed


def batched(records: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def collect_targets(records: list[dict[str, Any]], args: argparse.Namespace, kind: str) -> list[dict[str, Any]]:
    tracks = set(args.track or [])
    statuses = set(args.status or [])
    ids = set(args.id or [])
    recommendations = set(args.recommendation or [])
    selected: list[dict[str, Any]] = []
    # random：每筆會各自加權抽引擎，所以「已有 review」以任一引擎為準，避免同一篇被反覆補。
    def already_reviewed(record: dict[str, Any]) -> bool:
        if args.provider == "random":
            return has_any_review(record)
        return has_provider_review(record, args.provider)

    for record in records:
        if ids:
            if str(record.get("id") or "") not in ids:
                continue
            if args.missing_only and already_reviewed(record):
                continue
            selected.append(record)
            continue
        if args.missing_only and already_reviewed(record):
            continue
        if kind == "items":
            if not in_item_scope(record, tracks, statuses, args.workflow_scope):
                continue
        else:
            if not in_candidate_scope(record, tracks):
                continue
        triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
        if recommendations and triage.get("recommendation") not in recommendations:
            continue
        selected.append(record)
    if kind == "items" and not ids:
        selected.sort(key=target_recency, reverse=True)
        selected.sort(key=current_reading_rank)
    return selected[: args.limit] if args.limit else selected


def process_file(path: Path, kind: str, args: argparse.Namespace) -> tuple[int, int]:
    records = load_jsonl(path)
    targets = collect_targets(records, args, kind)
    if args.prepare_only or not targets:
        return len(targets), 0

    # 每筆獨立決定引擎：random 時逐筆加權抽，
    # 其餘沿用指定引擎。再依引擎分組，同組仍可分批送一次 CLI。
    if args.provider == "random":
        providers = available_providers()
        if not providers:
            raise RuntimeError("找不到可用的 Codex、Claude Code、Gemini 或 Ollama CLI。")
        assignments = [(weighted_choice(providers), record) for record in targets]
    else:
        assignments = [(args.provider, record) for record in targets]

    grouped: dict[str, list[dict[str, Any]]] = {}
    for provider, record in assignments:
        grouped.setdefault(provider, []).append(record)

    changed = 0
    for provider, group in grouped.items():
        for batch_records in batched(group, max(1, args.batch_size)):
            batch_input = [review_input(record) for record in batch_records]
            reviews = run_provider(batch_input, args, provider)
            batch_changed = apply_reviews(records, reviews, provider)
            changed += batch_changed
            if batch_changed and not args.dry_run:
                for record in records:
                    record.pop("_line", None)
                write_jsonl(path, records)
            print(
                f"{kind}: {provider_meta(provider)['label']} batch selected {len(batch_records)}, updated {batch_changed}",
                flush=True,
            )
    return len(targets), changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Use an AI CLI to add reading recommendations and summaries.")
    parser.add_argument("--provider", choices=sorted([*AI_PROVIDERS, "random"]), default="codex")
    parser.add_argument("--target", choices=["candidates", "items", "both"], default="candidates")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--track", action="append", default=[])
    parser.add_argument("--status", action="append", default=["inbox"])
    parser.add_argument("--recommendation", action="append", default=[], help="Only enrich candidates with this local triage recommendation. Can be repeated.")
    parser.add_argument("--id", action="append", default=[], help="Only enrich the record with this id. Can be repeated.")
    parser.add_argument("--workflow-scope", action="store_true", help="For items, include inbox plus reader/workflow statuses.")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--missing-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prepare-only", action="store_true", help="Only count records that would be sent to the selected AI CLI.")
    parser.add_argument("--dry-run", action="store_true", help="Call the selected AI CLI but do not write JSONL.")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    provider_label = (
        "隨機（Codex 35 / Claude 35 / Gemini 15 / Ollama 15，逐筆加權）"
        if args.provider == "random"
        else provider_meta(args.provider)["label"]
    )

    totals: list[tuple[str, int, int]] = []
    if args.target in {"candidates", "both"}:
        totals.append(("RSS 新進", *process_file(args.candidates, "candidates", args)))
    if args.target in {"items", "both"}:
        totals.append(("資料庫項目", *process_file(args.items, "items", args)))

    lines = [
        f"# {provider_label} review enrichment report",
        "",
        f"- Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Target: {args.target}",
        f"- Provider: {provider_label}",
        f"- Tracks: {', '.join(args.track) if args.track else 'all'}",
        f"- Mode: {'prepare only' if args.prepare_only else 'dry run' if args.dry_run else 'write'}",
        "",
    ]
    for label, selected, changed in totals:
        lines.append(f"- {label}: selected {selected}, updated {changed}")
    text = "\n".join(lines).rstrip() + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
