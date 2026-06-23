#!/usr/bin/env python3
"""編輯台雙引擎執行器。

可選 Claude CLI 或 Codex CLI 跑下列任務：
- theme-check     ：判斷所選材料適合「主題式」或「彙報式」，參考觀點筆記，沒有相關觀點時記一筆待補觀點。
- compose-thematic：把幾篇相關材料收斂成一篇帶觀點的 article 草稿。
- compose-digest  ：把多主題材料整理成彙報式 article 草稿。
- factcheck       ：對草稿/材料跑查核，列出值得收藏的查證來源。

建 prompt 時，每篇材料優先用 reading_metadata.translated_article_markdown_zh（翻譯全文）以省 token，
沒有才退而用 editorial_triage.zh_summary / summary。

結果 upsert 到 .cache/editor-sessions.jsonl，狀態寫 .cache/editor-status.json，供 local_web.py 輪詢。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
VIEWPOINTS = ROOT / "database" / "viewpoints.jsonl"
CACHE = ROOT / ".cache"
CANDIDATES = CACHE / "rss-candidates.jsonl"
SESSIONS = CACHE / "editor-sessions.jsonl"
STATUS = CACHE / "editor-status.json"

TASK_TYPES = {"theme-check", "compose-thematic", "compose-digest", "factcheck", "extract-viewpoints"}
CHOICE_LABELS = {"thematic": "主題式", "digest": "彙報式"}
TASK_LABELS = {
    "theme-check": "選法檢查",
    "compose-thematic": "主題式撰稿",
    "compose-digest": "彙報式撰稿",
    "factcheck": "查核找原文",
    "extract-viewpoints": "萃取觀點",
}
# 哪些任務要上網查（需要 web search 工具）
WEB_TASKS = {"factcheck"}


# --------------------------------------------------------------------------- #
# 基礎 helper（自含，與 codex_translate_article.py 風格一致）
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object, limit: int | None = None) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    text = "\n".join(line for line in text.split("\n") if line.strip()).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def upsert_jsonl(path: Path, record: dict[str, Any], key: str = "id") -> None:
    records = load_jsonl(path)
    out, replaced = [], False
    for existing in records:
        if existing.get(key) == record.get(key):
            out.append(record)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(record)
    write_jsonl(path, out)


def write_status(payload: dict[str, Any]) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 材料與觀點存取
# --------------------------------------------------------------------------- #
def find_records(ids: list[str]) -> list[dict[str, Any]]:
    pool = {clean_text(r.get("id")): r for r in load_jsonl(ITEMS)}
    for r in load_jsonl(CANDIDATES):
        pool.setdefault(clean_text(r.get("id")), r)
    found = []
    for i in ids:
        rec = pool.get(clean_text(i))
        if rec:
            found.append(rec)
    return found


def record_title(record: dict[str, Any]) -> str:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    model_titles = []
    for key in ("codex_review", "claude_review"):
        review = editorial.get(key) if isinstance(editorial.get(key), dict) else {}
        model_titles.append(review.get("zh_title"))
    return (
        clean_text(record.get("editorial_title"), 320)
        or clean_text(metadata.get("editorial_title"), 320)
        or next((title for title in (clean_text(value, 320) for value in model_titles) if title), "")
        or clean_text(editorial.get("zh_title"), 320)
        or clean_text(editorial.get("codex_zh_title"), 320)
        or clean_text(metadata.get("translated_zh_title"), 320)
        or clean_text(record.get("title"), 320)
        or clean_text(record.get("url"), 320)
        or clean_text(record.get("id"), 320)
    )


def translated_markdown(record: dict[str, Any]) -> str:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    for key in (
        "codex_translated_article_markdown_zh",
        "translated_article_markdown_zh",
        "claude_translated_article_markdown_zh",
    ):
        text = clean_text(metadata.get(key), 12000)
        if text:
            return text
    return ""


def material_block(record: dict[str, Any]) -> dict[str, Any]:
    """單篇材料的精簡 context；優先用翻譯全文以省 token。"""
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    translated = translated_markdown(record)
    if translated:
        body, body_kind = translated, "translated_full"
    else:
        body = clean_text(editorial.get("zh_summary"), 2400) or clean_text(record.get("summary"), 2400)
        body_kind = "summary"
    return {
        "id": clean_text(record.get("id")),
        "title": record_title(record),
        "track": clean_text(record.get("track")),
        "tags": [clean_text(t) for t in (record.get("tags") or []) if clean_text(t)],
        "url": clean_text(record.get("url")),
        "source_name": clean_text(record.get("source_name")),
        "body_kind": body_kind,
        "body": body,
    }


def personal_note_text(record: dict[str, Any]) -> str:
    notes = record.get("personal_notes")
    if isinstance(notes, dict):
        return clean_text(notes.get("body"))
    return clean_text(notes)


def gather_viewpoints(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """觀點語料 = database/viewpoints.jsonl（使用者寫的優先）+ 所選材料的 personal_notes。"""
    out: list[dict[str, Any]] = []
    for vp in load_jsonl(VIEWPOINTS):
        body = clean_text(vp.get("body"), 1200)
        if not body:
            continue
        out.append(
            {
                "id": clean_text(vp.get("id")),
                "title": clean_text(vp.get("title"), 200),
                "tags": [clean_text(t) for t in (vp.get("tags") or []) if clean_text(t)],
                "body": body,
                "source": clean_text(vp.get("source")) or "user",
            }
        )
    for rec in records:
        note = personal_note_text(rec)
        if note:
            out.append(
                {
                    "id": f"note:{clean_text(rec.get('id'))}",
                    "title": f"材料筆記：{record_title(rec)}",
                    "tags": [clean_text(t) for t in (rec.get("tags") or []) if clean_text(t)],
                    "body": clean_text(note, 1200),
                    "source": "personal_note",
                }
            )
    return out


# --------------------------------------------------------------------------- #
# Prompt 與 schema
# --------------------------------------------------------------------------- #
WRITING_RULES = (
    "寫作規則（Ian Open News）：忠於來源、分清「原文說什麼」與「我們的觀察」；"
    "用台灣慣用語、不超譯；語氣清楚準確不浮誇；數字、日期、組織、法規、授權名稱保留來源，不確定就標「需要出處」；"
    "不要把廠商新聞稿當已證實事實。"
)
# 不需上網的任務，明確要求只靠提供的材料推理。
OFFLINE_RULE = "不要上網、不要使用任何工具，只根據提供的材料推理。"


def theme_check_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "coherence",
            "recommended_choice",
            "matches_user_choice",
            "rationale",
            "posting_suggestion",
            "angle_suggestions",
            "used_viewpoint_ids",
            "has_suggested_viewpoint",
            "suggested_viewpoint_title",
            "suggested_viewpoint_body",
        ],
        "properties": {
            "coherence": {"type": "string", "enum": ["high", "medium", "low"]},
            "recommended_choice": {"type": "string", "enum": ["thematic", "digest"]},
            "matches_user_choice": {"type": "boolean"},
            "rationale": {"type": "string"},
            "posting_suggestion": {"type": "string"},
            "angle_suggestions": {"type": "array", "items": {"type": "string"}},
            "used_viewpoint_ids": {"type": "array", "items": {"type": "string"}},
            "has_suggested_viewpoint": {"type": "boolean"},
            "suggested_viewpoint_title": {"type": "string"},
            "suggested_viewpoint_body": {"type": "string"},
        },
    }


def factcheck_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["claims", "recommended_sources", "overall_note"],
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim", "status", "note"],
                    "properties": {
                        "claim": {"type": "string"},
                        "status": {"type": "string", "enum": ["supported", "unclear", "needs-source"]},
                        "note": {"type": "string"},
                    },
                },
            },
            "recommended_sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "url", "kind", "found", "why"],
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "kind": {"type": "string",
                                  "enum": ["original", "primary", "official", "follow-up", "background"]},
                        "found": {"type": "boolean"},
                        "why": {"type": "string"},
                    },
                },
            },
            "overall_note": {"type": "string"},
        },
    }


def extract_viewpoints_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["viewpoint_candidates"],
        "properties": {
            "viewpoint_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "body"],
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                    },
                },
            },
        },
    }


def build_prompt(task_type: str, choice: str, materials: list[dict], viewpoints: list[dict], instructions: str) -> str:
    mat_json = json.dumps(materials, ensure_ascii=False, indent=2)
    vp_json = json.dumps(viewpoints, ensure_ascii=False, indent=2)
    extra = f"\n額外指示：{instructions}\n" if instructions else ""
    choice_label = CHOICE_LABELS.get(choice, choice or "未指定")

    if task_type == "theme-check":
        return f"""你是 Ian Open News 的選題編輯。使用者挑了下面幾篇材料，原本想用「{choice_label}」的方式貼文。
請判斷這些材料彼此相關程度，建議用「主題式」（thematic，幾篇相關、收斂成一個觀點）還是「彙報式」（digest，多主題不一定相關的彙整），
並說明若選錯該怎麼貼。判斷時請參考使用者的觀點筆記；如果沒有任何一條觀點和這批材料相關，請在 has_suggested_viewpoint=true 並擬一條待補觀點草稿（標題＋一兩句）。

{WRITING_RULES}{OFFLINE_RULE}
{extra}
材料：
{mat_json}

觀點筆記（可能為空）：
{vp_json}

請只輸出符合下列 JSON schema 的物件，不要任何額外說明或 markdown 包裝：
{json.dumps(theme_check_schema(), ensure_ascii=False)}
"""

    if task_type in {"compose-thematic", "compose-digest"}:
        mode = "主題式：把這幾篇相關材料收斂成一篇帶清楚觀點的稿，三段分明（原文重點／我們的觀察／後續建議）。" \
            if task_type == "compose-thematic" else \
            "彙報式：把多則不一定相關的材料整理成 roundup，每則一個小段，標清楚各自來源與重點，最後給一段總觀察。"
        vp_hint = "請參考並延續下列觀點筆記的立場；" if viewpoints else "目前沒有相關觀點筆記，請在文末用『（待補觀點）』標出本篇可以發展的立場；"
        return f"""你是 Ian Open News 的撰稿編輯。請用繁體中文（台灣用語）寫一篇{CHOICE_LABELS.get(choice, '')} article 草稿。
{mode}
{vp_hint}保留每篇材料的來源與原始連結。

{WRITING_RULES}{OFFLINE_RULE}
{extra}
材料：
{mat_json}

觀點筆記（可能為空）：
{vp_json}

請直接輸出 Markdown 稿件本文（含標題），不要輸出 JSON、不要加說明。
"""

    if task_type == "extract-viewpoints":
        return f"""你是 Ian Open News 的觀點整理編輯。請從下列材料（以及「額外指示」中可能附上的本次編輯內容）中，
萃取 2-5 條值得存進「觀點庫」的觀點。每條給一個短標題與一兩句 body，要能把這些材料串起來、講清楚一個立場或張力，
不是流水帳摘要。避免空泛口號。

{WRITING_RULES}{OFFLINE_RULE}
{extra}
材料：
{mat_json}

請只輸出符合下列 JSON schema 的物件，不要任何額外說明或 markdown 包裝：
{json.dumps(extract_viewpoints_schema(), ensure_ascii=False)}
"""

    # factcheck：真的上網把原文 / 正式文件 / 系列下篇找出來，附真實可點 URL
    input_urls = [m.get("url") for m in materials if m.get("url")]
    input_urls_json = json.dumps(input_urls, ensure_ascii=False)
    return f"""你是 Ian Open News 的查核編輯，可以使用網路搜尋工具。請**實際上網查證**，幫使用者把原文找出來。

任務：
1. 列出材料裡可驗證的關鍵宣稱（claims），標記是否被材料本身支持。
2. recommended_sources：上網找出**能佐證或追溯的原始/權威來源**並附**真實、可點的 URL**——例如官方公告、法規原文、統計報告、研究原文、新聞原始出處。
   - kind 標明來源性質：original（被轉述報導的原始出處）/ primary（一手文件、官方公告、法規）/ official（機關或組織官網統計或公告）/ follow-up（系列文章的下一篇或其他篇）/ background（補充背景）。
   - 若材料看起來是系列文章（標題或內文出現「上篇 / part 1 / parte 1 / 第一部」等），請找出**後續或其他篇**，kind=follow-up。
   - found：真的找到可點 URL 時為 true 並填 url；查不到就 found=false、url 留空字串，並在 why 說明為何沒找到，**絕對不要杜撰 URL**。
3. **不要把使用者提供的材料本身列為 recommended_sources**（那是被查核的對象，不是新發現）。以下是材料的 URL，請排除指向同一頁的連結：{input_urls_json}

{WRITING_RULES}
{extra}
材料：
{mat_json}

請只輸出符合下列 JSON schema 的物件，不要任何額外說明或 markdown 包裝：
{json.dumps(factcheck_schema(), ensure_ascii=False)}
"""


# --------------------------------------------------------------------------- #
# 引擎呼叫
# --------------------------------------------------------------------------- #
def cli_path(name: str) -> str:
    candidate = shutil.which(name)
    if candidate:
        return candidate
    for path in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if Path(path).exists():
            return path
    raise RuntimeError(f"找不到 {name} CLI，請先確認是否已安裝。")


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    return env


def run_codex(prompt: str, schema: dict | None, timeout: int, web: bool = False) -> tuple[str, str]:
    """回傳 (raw_text, model)。有 schema 時 raw_text 為 JSON 字串。"""
    CACHE.mkdir(exist_ok=True)
    output_path = CACHE / "editor-codex-output.txt"
    command = [
        cli_path("codex"), "-a", "never", "exec", "--ephemeral",
        "--cd", str(ROOT), "--sandbox", "read-only", "--color", "never",
        "--output-last-message", str(output_path),
    ]
    if web:
        command += ["-c", "tools.web_search=true"]
    if schema is not None:
        schema_path = CACHE / "editor-codex.schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
        command += ["--output-schema", str(schema_path)]
    command += ["-"]
    result = subprocess.run(
        command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=_env()
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex exec failed\nSTDOUT:\n{result.stdout[-2000:]}\nSTDERR:\n{result.stderr[-2000:]}")
    text = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout
    return text.strip(), "codex"


def run_claude(prompt: str, timeout: int, web: bool = False) -> tuple[str, str]:
    """回傳 (result_text, model)。"""
    command = [cli_path("claude"), "-p", prompt, "--output-format", "json"]
    if web:
        command += ["--allowedTools", "WebSearch", "WebFetch"]
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, env=_env()
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude failed\nSTDOUT:\n{result.stdout[-2000:]}\nSTDERR:\n{result.stderr[-2000:]}")
    payload = json.loads(result.stdout)
    if payload.get("is_error"):
        raise RuntimeError(f"claude returned error: {payload.get('result')}")
    model = ""
    usage = payload.get("modelUsage")
    if isinstance(usage, dict) and usage:
        model = sorted(usage.keys())[-1]
    return clean_text_keep_markdown(payload.get("result")), model


def clean_text_keep_markdown(value: object) -> str:
    return str(value or "").strip()


def parse_json_result(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw = raw[start : end + 1]
    return json.loads(raw)


# --------------------------------------------------------------------------- #
# 輸出 → 可讀 markdown
# --------------------------------------------------------------------------- #
def theme_check_markdown(data: dict, choice: str) -> str:
    rec = data.get("recommended_choice")
    lines = [
        f"## 選法檢查結果",
        "",
        f"- 你選的：**{CHOICE_LABELS.get(choice, choice or '未指定')}**",
        f"- 建議：**{CHOICE_LABELS.get(rec, rec)}**"
        + ("（與你的選擇一致）" if data.get("matches_user_choice") else "（建議調整）"),
        f"- 材料相關程度：{ {'high':'高','medium':'中','low':'低'}.get(data.get('coherence'), data.get('coherence')) }",
        "",
        f"**理由**：{data.get('rationale','')}",
        "",
        f"**貼法建議**：{data.get('posting_suggestion','')}",
        "",
        "**可切角度**：",
    ]
    for a in data.get("angle_suggestions") or []:
        lines.append(f"- {a}")
    if data.get("has_suggested_viewpoint"):
        lines += [
            "",
            "**待補觀點（沒有相關觀點筆記，已自動記一筆草稿）**：",
            f"- {data.get('suggested_viewpoint_title','')}：{data.get('suggested_viewpoint_body','')}",
        ]
    return "\n".join(lines)


KIND_LABELS = {"original": "原始出處", "primary": "一手文件", "official": "官方",
               "follow-up": "系列下篇", "background": "背景"}


def factcheck_markdown(data: dict) -> str:
    lines = ["## 查核找原文", "", "**關鍵宣稱**："]
    badge = {"supported": "✅ 有支持", "unclear": "❓ 不明", "needs-source": "⚠️ 需出處"}
    for c in data.get("claims") or []:
        lines.append(f"- {badge.get(c.get('status'), c.get('status'))}：{c.get('claim','')}　{c.get('note','')}")
    found = [s for s in (data.get("recommended_sources") or []) if s.get("url")]
    missing = [s for s in (data.get("recommended_sources") or []) if not s.get("url")]
    lines += ["", "**找到的原文／來源**（可在介面按「+ 新增到入庫建檔區」）："]
    if found:
        for s in found:
            kind = KIND_LABELS.get(s.get("kind"), s.get("kind") or "")
            tag = f"［{kind}］" if kind else ""
            lines.append(f"- {tag}[{s.get('title') or s.get('url')}]({s.get('url')})　{s.get('why','')}")
    else:
        lines.append("- （這次沒找到可點的原文連結）")
    if missing:
        lines += ["", "**還沒找到原文（誠實標記，未杜撰連結）**："]
        for s in missing:
            kind = KIND_LABELS.get(s.get("kind"), s.get("kind") or "")
            tag = f"［{kind}］" if kind else ""
            lines.append(f"- {tag}{s.get('title','')}　{s.get('why','')}")
    if data.get("overall_note"):
        lines += ["", f"**整體**：{data.get('overall_note')}"]
    return "\n".join(lines)


def extract_viewpoints_markdown(data: dict) -> str:
    lines = ["## 萃取的觀點候選", "", "（可在下方按「+ 串聯加入觀點庫」，會自動帶上本次材料）", ""]
    for v in data.get("viewpoint_candidates") or []:
        lines.append(f"- **{v.get('title','')}**：{v.get('body','')}")
    if len(lines) == 4:
        lines.append("- （這次沒萃取到明確觀點）")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _norm_url(url: object) -> str:
    u = clean_text(url).lower().rstrip("/")
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"[?#].*$", "", u)
    return u


def drop_input_echoes(sources: object, materials: list[dict]) -> list[dict]:
    """濾掉把輸入材料自己當推薦的來源（echo）。"""
    if not isinstance(sources, list):
        return []
    input_urls = {_norm_url(m.get("url")) for m in materials if m.get("url")}
    out = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        if s.get("url") and _norm_url(s.get("url")) in input_urls:
            continue
        out.append(s)
    return out


def maybe_record_suggested_viewpoint(data: dict, records: list[dict], dry_run: bool) -> str | None:
    if not data.get("has_suggested_viewpoint"):
        return None
    title = clean_text(data.get("suggested_viewpoint_title"), 200)
    body = clean_text(data.get("suggested_viewpoint_body"), 1200)
    if not body:
        return None
    vp_id = "vp-" + uuid.uuid4().hex[:12]
    tags: list[str] = []
    for rec in records:
        tags += [clean_text(t) for t in (rec.get("tags") or []) if clean_text(t)]
    record = {
        "id": vp_id,
        "title": title or "（待補觀點）",
        "tags": sorted(set(tags)),
        "body": body,
        "source": "suggested",
        "status": "pending",
        "related_item_ids": [clean_text(r.get("id")) for r in records],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    if not dry_run:
        append_jsonl(VIEWPOINTS, record)
    return vp_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Ian Open News 編輯台雙引擎任務執行器")
    parser.add_argument("--engine", choices=["claude", "codex"], required=True)
    parser.add_argument("--task-type", choices=sorted(TASK_TYPES), required=True)
    parser.add_argument("--items", default="", help="逗號分隔的 item id")
    parser.add_argument("--choice", choices=["thematic", "digest"], default="")
    parser.add_argument("--instructions", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session_id = args.session_id or ("sess-" + uuid.uuid4().hex[:12])
    ids = [s for s in (p.strip() for p in args.items.split(",")) if s]
    write_status({"session_id": session_id, "state": "running",
                  "message": f"正在執行：{TASK_LABELS.get(args.task_type, args.task_type)}（{args.engine}）",
                  "started_at": now_iso()})

    try:
        records = find_records(ids)
        if not records:
            raise SystemExit("找不到任何指定的材料 id。")
        materials = [material_block(r) for r in records]
        viewpoints = gather_viewpoints(records) if args.task_type in {"theme-check", "compose-thematic", "compose-digest"} else []
        prompt = build_prompt(args.task_type, args.choice, materials, viewpoints, args.instructions)

        schema_for = {
            "theme-check": theme_check_schema(),
            "factcheck": factcheck_schema(),
            "extract-viewpoints": extract_viewpoints_schema(),
        }
        schema = schema_for.get(args.task_type)
        web = args.task_type in WEB_TASKS

        if args.engine == "codex":
            raw, model = run_codex(prompt, schema, args.timeout, web=web)
        else:
            raw, model = run_claude(prompt, args.timeout, web=web)

        data: dict[str, Any] | None = None
        suggested_vp_id = None
        if args.task_type == "theme-check":
            data = parse_json_result(raw)
            suggested_vp_id = maybe_record_suggested_viewpoint(data, records, args.dry_run)
            output_markdown = theme_check_markdown(data, args.choice)
        elif args.task_type == "factcheck":
            data = parse_json_result(raw)
            data["recommended_sources"] = drop_input_echoes(data.get("recommended_sources"), materials)
            output_markdown = factcheck_markdown(data)
        elif args.task_type == "extract-viewpoints":
            data = parse_json_result(raw)
            output_markdown = extract_viewpoints_markdown(data)
        else:
            output_markdown = raw

        session = {
            "id": session_id,
            "created_at": now_iso(),
            "engine": args.engine,
            "model": model,
            "task_type": args.task_type,
            "task_label": TASK_LABELS.get(args.task_type, args.task_type),
            "choice": args.choice,
            "item_ids": [clean_text(r.get("id")) for r in records],
            "item_titles": [record_title(r) for r in records],
            "used_translation": [m["id"] for m in materials if m["body_kind"] == "translated_full"],
            "input_summary": "；".join(record_title(r) for r in records)[:400],
            "output_markdown": output_markdown,
            "output_data": data,
            "suggested_viewpoint_id": suggested_vp_id,
            "status": "done",
        }
        if not args.dry_run:
            upsert_jsonl(SESSIONS, session)
        write_status({"session_id": session_id, "state": "done",
                      "message": "完成", "finished_at": now_iso()})
        print(json.dumps({"session_id": session_id, "engine": args.engine, "model": model,
                          "task_type": args.task_type, "suggested_viewpoint_id": suggested_vp_id,
                          "dry_run": args.dry_run}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        write_status({"session_id": session_id, "state": "failed",
                      "message": f"執行失敗：{exc}", "finished_at": now_iso()})
        raise


if __name__ == "__main__":
    main()
