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

from page_metadata import is_access_prompt_text


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
REPORT = ROOT / ".cache" / "codex-review-report.md"
TASTE_PROFILE = ROOT / "database" / "taste-profile.json"

READER_STATUSES = {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}
READER_ACTIONS = {"accepted-for-editing", "direct-pr-small-news", "revisit-with-personal-notes"}
CURRENT_READING_PRIORITY_DAYS = 1
DEFAULT_OLLAMA_MODEL = "TwinkleAI/gemma-3-4B-T1-it"
OLLAMA_MODELS = {
    "ollama": DEFAULT_OLLAMA_MODEL,
    "ollama-gemma4": "gemma4:12b-mlx",
    "ollama-twinkle": "TwinkleAI/gemma-3-4B-T1-it",
}
ACTIVE_PROVIDER_ORDER = ["codex", "claude", "gemini", "ollama-gemma4", "ollama-twinkle"]
# 隨機（--provider random）時每筆獨立抽引擎的加權比例。
PROVIDER_WEIGHTS = {"codex": 30, "claude": 30, "gemini": 15, "ollama-gemma4": 13, "ollama-twinkle": 12}
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
    "ollama-gemma4": {
        "label": "Ollama gemma4:12b MLX",
        "review_key": "ollama_gemma4_review",
        "generated_key": "ollama_gemma4_generated_at",
        "generator": "ollama-cli",
        "model": "gemma4:12b-mlx",
    },
    "ollama-twinkle": {
        "label": "TwinkleAI:Gemma-3-4B-T1-IT",
        "review_key": "ollama_twinkle_review",
        "generated_key": "ollama_twinkle_generated_at",
        "generator": "ollama-cli",
        "model": "TwinkleAI/gemma-3-4B-T1-it",
    },
}

TAIWAN_DIRECT_SIGNAL_RE = re.compile(
    r"台灣|臺灣|台北|臺北|Taiwan(?:ese)?|Taipei|Republic of China|\bROC\b|\.tw\b",
    re.I,
)
TAIWAN_OUTPUT_SIGNAL_RE = re.compile(
    r"台灣|臺灣|台北|臺北|Taiwan(?:ese)?|Taipei|中華電信|台積電|TSMC|數位發展部|國發會|行政院|立法院|本土(?:企業|公司|團隊|廠商|電信|產業)",
    re.I,
)
TAIWAN_SAFE_CONTEXT_RE = re.compile(
    r"(?:未見|沒有|缺少|無|非).{0,12}(?:台灣|臺灣|Taiwan|Taipei)"
    r"|(?:台灣|臺灣).{0,12}(?:比較參考|參考案例|讀者)"
    r"|(?:可作|作為|只能作為|只能視為).{0,16}(?:台灣|臺灣).{0,16}(?:比較|參考)",
    re.I,
)
TAIWAN_FACT_CLAIM_RE = re.compile(
    r"(?:台灣|臺灣|Taiwan(?:ese)?|Taipei)(?:的)?(?:團隊|企業|公司|廠商|組織|政府|法規|法制|案例|部署|產業|半導體|電信)"
    r"|(?:由|來自|面向|針對).{0,8}(?:台灣|臺灣|Taiwan(?:ese)?|Taipei).{0,8}(?:開發|推出|採用|部署)"
    r"|(?:中華電信|台積電|TSMC|數位發展部|國發會|行政院|立法院)"
    r"|本土(?:企業|公司|團隊|廠商|電信|產業)",
    re.I,
)
TAIWAN_GUARD_FALLBACK = "原文未見直接台灣關聯；若要保留，只能作為比較政策、治理概念或技術架構參考。"


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


def write_status(path: Path | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
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


def ollama_model(provider: str = "ollama") -> str:
    default = OLLAMA_MODELS.get(provider, DEFAULT_OLLAMA_MODEL)
    model = (os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_CLI_MODEL") or default).strip()
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


def terminal_clean_text(text: str) -> str:
    """Render common terminal control sequences so captured CLI output is parseable."""
    lines: list[str] = []
    line: list[str] = []
    cursor = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\x1b":
            match = re.match(r"\x1b\[([0-9;?]*)([A-Za-z])", text[index:])
            if match:
                params = match.group(1)
                command = match.group(2)
                first_param = params.split(";", 1)[0].lstrip("?") if params else ""
                amount = int(first_param) if first_param.isdigit() else 1
                if command == "K":
                    del line[cursor:]
                elif command == "D":
                    cursor = max(0, cursor - amount)
                elif command == "C":
                    cursor = min(len(line), cursor + amount)
                index += len(match.group(0))
                continue
            index += 1
            continue
        if char == "\r":
            cursor = 0
        elif char == "\n":
            lines.append("".join(line).rstrip())
            line = []
            cursor = 0
        elif ord(char) < 32 and char not in {"\t"}:
            pass
        else:
            while cursor > len(line):
                line.append(" ")
            if cursor == len(line):
                line.append(char)
            else:
                line[cursor] = char
            cursor += 1
        index += 1
    lines.append("".join(line).rstrip())
    return "\n".join(lines)


def escape_json_string_newlines(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
            continue
        if escaped:
            out.append(char)
            escaped = False
        elif char == "\\":
            out.append(char)
            escaped = True
        elif char == '"':
            out.append(char)
            in_string = False
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        else:
            out.append(char)
    return "".join(out)


def prepare_json_candidate(text: str) -> str:
    return escape_json_string_newlines(terminal_clean_text(text)).strip()


def json_text_candidates(raw: str) -> list[str]:
    candidates = [raw]
    for fence_match in re.finditer(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.S | re.I):
        fenced = fence_match.group(1).strip()
        if fenced:
            candidates.insert(0, fenced)
    object_match = re.search(r"\{.*\}", raw, flags=re.S)
    if object_match:
        candidates.append(object_match.group(0).strip())
    last_line = next((line.strip() for line in reversed(raw.splitlines()) if line.strip()), "")
    if last_line and last_line not in candidates:
        candidates.append(last_line)

    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char not in "[{":
            continue
        try:
            _, end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        candidate = raw[index : index + end].strip()
        if candidate:
            candidates.append(candidate)
    return candidates


def load_json_from_text(text: str) -> Any:
    raw = prepare_json_candidate(text)
    if not raw:
        raise RuntimeError("model output is empty")
    decoded: list[Any] = []
    seen: set[str] = set()
    last_error = ""
    for candidate in json_text_candidates(raw):
        prepared = prepare_json_candidate(candidate)
        if not prepared or prepared in seen:
            continue
        seen.add(prepared)
        try:
            decoded.append(json.loads(prepared))
        except json.JSONDecodeError as exc:
            last_error = f"{exc.msg} at character {exc.pos}"
            continue
    if decoded:
        for payload in decoded:
            if isinstance(payload, dict) and any(key in payload for key in ("reviews", "result", "message", "response")):
                return payload
        return decoded[0]
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"model output missing valid JSON payload{detail}")


def parse_cli_json(raw: str) -> dict[str, Any]:
    payload = load_json_from_text(raw)
    if isinstance(payload, str):
        payload = load_json_from_text(payload)
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
    if isinstance(payload, dict) and "response" in payload and isinstance(payload["response"], str):
        response_payload = load_json_from_text(payload["response"])
        if isinstance(response_payload, dict):
            return response_payload
    if isinstance(payload, dict) and "message" in payload and isinstance(payload["message"], dict):
        content = payload["message"].get("content")
        if isinstance(content, str):
            content_payload = load_json_from_text(content)
            if isinstance(content_payload, dict):
                return content_payload
        return payload["message"]
    raise RuntimeError("model output missing structured payload")


def available_providers() -> list[str]:
    available: list[str] = []
    for provider in ACTIVE_PROVIDER_ORDER:
        finder = {"codex": codex_path, "claude": claude_path, "gemini": agy_path}.get(provider, ollama_path)
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
    if is_access_prompt_text(article_text):
        article_text = ""
    if article_text:
        return article_text, "主文全文", False

    sentences = enrichment.get("summary_sentences")
    if isinstance(sentences, list):
        text = clean_text("\n".join(str(sentence) for sentence in sentences if sentence), 2200)
        if text:
            return text, "已抽取正文摘要", True

    summary = clean_text(record.get("summary"), 2200)
    if is_access_prompt_text(summary):
        summary = ""
    description = clean_text(reading.get("description"), 1200)
    if is_access_prompt_text(description):
        description = ""
    if summary and description and description not in summary:
        return f"{summary}\n{description}", "RSS 摘要與頁面描述", True
    if summary:
        return summary, "RSS 摘要", True
    if description:
        return description, "頁面描述", True

    title = clean_text(record.get("title"), 500)
    return title, "只有標題", True


def direct_taiwan_signal_text(record: dict[str, Any]) -> str:
    reading = record.get("reading_metadata")
    reading = reading if isinstance(reading, dict) else {}
    text, _basis, _needs_fulltext = source_material(record)
    parts: list[str] = [
        clean_text(record.get("title"), 500),
        clean_text(record.get("url"), 500),
        clean_text(record.get("source_name"), 240),
        clean_text(record.get("summary"), 1500),
        " ".join(str(tag) for tag in record.get("tags", []) if tag),
        text,
        clean_text(reading.get("description"), 1200),
        clean_text(reading.get("site_name"), 240),
        clean_text(reading.get("original_site_title"), 500),
        clean_text(reading.get("final_url"), 500),
        clean_text(reading.get("source_url"), 500),
    ]
    return "\n".join(part for part in parts if part)


def has_direct_taiwan_signal(record: dict[str, Any]) -> bool:
    return bool(TAIWAN_DIRECT_SIGNAL_RE.search(direct_taiwan_signal_text(record)))


def split_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+", text)
    return [part for part in parts if part]


def has_unsupported_taiwan_context(text: object) -> bool:
    value = clean_text(text)
    if not value or not TAIWAN_OUTPUT_SIGNAL_RE.search(value):
        return False
    return not bool(TAIWAN_SAFE_CONTEXT_RE.search(value))


def sanitize_unsupported_taiwan_context(text: object) -> tuple[str, bool, bool]:
    value = clean_text(text)
    if not has_unsupported_taiwan_context(value):
        return value, False, False
    fact_claim = bool(TAIWAN_FACT_CLAIM_RE.search(value))
    sentences = split_sentences(value)
    kept = [sentence for sentence in sentences if not has_unsupported_taiwan_context(sentence)]
    if kept and len(kept) < len(sentences):
        return clean_text("".join(kept)), True, fact_claim
    return TAIWAN_GUARD_FALLBACK, True, fact_claim


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
        lines.append(
            "台灣脈絡是優先檢查項，不是可補造的事實；source_text 沒有直接台灣線索時，"
            "只能寫「未見直接台灣關聯」或「可作台灣比較參考」。"
        )
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

請在判斷 recommendation / confidence / content_kind 時把上述品味納入考量；命中偏好主題，或原文有明確台灣切角的，傾向 recommend-collect 或 recommend-review，不要輕易 skip。
"""


def build_prompt(batch: list[dict[str, Any]], provider: str = "codex") -> str:
    label = provider_meta(provider)["label"]
    data = json.dumps({"items": batch}, ensure_ascii=False, indent=2)
    taste = taste_profile_block()
    return f"""你是 Ian Open News 的編輯助理，請為下列 RSS/知識項目補上 {label} 版閱讀建議。
{taste}

請只根據每筆提供的 source_text 判斷，不要上網，不要補不存在的事實。
若 source_basis 是「只有標題」或 source_text 太短，請明確降低 confidence，needs_fulltext 設為 true，摘要只做保守判斷。

台灣脈絡防幻覺規則：
- 只有 source_text、標題、來源或 URL 明示台灣 / 臺灣 / Taiwan / Taipei / .tw 等直接線索時，才可把台灣人物、組織、企業、團隊、政策、法規、案例或部署寫成事實。
- 若沒有直接台灣線索，不得宣稱「台灣團隊」「台灣企業」「台灣案例」「台灣政策」或自行代入中華電信、台積電、半導體等台灣產業角色。
- 沒有直接台灣線索但議題有參考價值時，只能說「未見直接台灣關聯，但可作台灣比較政策 / 治理概念 / 技術架構參考」。

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


def run_ollama(batch: list[dict[str, Any]], args: argparse.Namespace, provider: str = "ollama") -> list[dict[str, Any]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(batch, provider)
    prompt += f"\n\n請務必只輸出 JSON 物件，且完全符合以下 JSON Schema，不要任何額外說明或 markdown 包裝：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    safe_provider = re.sub(r"[^a-z0-9_-]+", "-", provider.lower())
    (cache / f"{safe_provider}-review-prompt.json").write_text(prompt, encoding="utf-8")
    model = ollama_model(provider)
    command = [
        ollama_path(),
        "run",
        model,
        "--format",
        "json",
        "--nowordwrap",
        "--hidethinking",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=args.timeout,
            env=cli_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{provider_meta(provider)['label']}（model: {model}）執行超過 {args.timeout} 秒，"
            "請縮小批次、拉長 timeout，或改用其他 AI CLI。"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"ollama run failed（model: {model}）\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    output_path = cache / f"{safe_provider}-review-output.json"
    output_path.write_text(result.stdout, encoding="utf-8")
    try:
        payload = parse_cli_json(result.stdout)
    except RuntimeError as exc:
        output_tail = terminal_clean_text(result.stdout)[-1200:].strip()
        tail_note = f"\nOUTPUT TAIL:\n{output_tail}" if output_tail else ""
        raise RuntimeError(
            f"{provider_meta(provider)['label']}（model: {model}）輸出不是可用的閱讀建議 JSON：{exc}。"
            f"原始輸出已保存到 {output_path.relative_to(ROOT)}。{tail_note}"
        ) from exc
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("Ollama output missing reviews array")
    return reviews


def run_provider(batch: list[dict[str, Any]], args: argparse.Namespace, provider: str) -> list[dict[str, Any]]:
    if provider == "claude":
        return run_claude(batch, args)
    if provider == "gemini":
        return run_gemini(batch, args)
    if provider.startswith("ollama"):
        return run_ollama(batch, args, provider)
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


def clear_existing_model_reviews(editorial: dict[str, Any]) -> None:
    for meta in AI_PROVIDERS.values():
        editorial.pop(meta["review_key"], None)
        editorial.pop(meta["generated_key"], None)
    for key in ["zh_title", "zh_summary", "summary_reason"]:
        editorial.pop(key, None)


def apply_taiwan_context_guard(record: dict[str, Any], provider_review: dict[str, Any]) -> None:
    if has_direct_taiwan_signal(record):
        return

    sanitized_fields: list[str] = []
    fact_claim = False
    for field in ("zh_title", "one_line_recommendation", "summary", "note"):
        original = provider_review.get(field)
        sanitized, changed, field_fact_claim = sanitize_unsupported_taiwan_context(original)
        if changed:
            provider_review[field] = sanitized
            sanitized_fields.append(field)
            fact_claim = fact_claim or field_fact_claim

    sanitized_reasons: list[str] = []
    reasons_changed = False
    for reason in provider_review.get("reasons", []):
        sanitized, changed, field_fact_claim = sanitize_unsupported_taiwan_context(reason)
        sanitized_reasons.append(sanitized)
        if changed:
            reasons_changed = True
            fact_claim = fact_claim or field_fact_claim
    if reasons_changed:
        provider_review["reasons"] = sanitized_reasons
        sanitized_fields.append("reasons")

    if not sanitized_fields:
        return

    guard_note = "防幻覺提醒：原文未見直接台灣訊號；已移除或改寫未支持的台灣關聯。"
    existing_note = clean_text(provider_review.get("note"), 500)
    if guard_note not in existing_note:
        provider_review["note"] = clean_text(f"{guard_note} {existing_note}", 500)
    if fact_claim:
        provider_review["confidence"] = "low"
    elif provider_review.get("confidence") == "high":
        provider_review["confidence"] = "medium"
    provider_review["taiwan_context_guard"] = {
        "status": "no-direct-taiwan-signal",
        "action": "sanitized-unsupported-context",
        "fields": sanitized_fields,
        "fact_claim": fact_claim,
    }


def apply_reviews(records: list[dict[str, Any]], reviews: list[dict[str, Any]], provider: str, replace_existing: bool = False) -> int:
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
        if replace_existing:
            clear_existing_model_reviews(editorial)
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
        if meta.get("model"):
            provider_review["model"] = meta["model"]
        apply_taiwan_context_guard(record, provider_review)
        editorial[meta["review_key"]] = provider_review
        has_codex = isinstance(editorial.get("codex_review"), dict)
        if provider == "codex" or not has_codex:
            editorial["zh_title"] = provider_review["zh_title"] or clean_text(record.get("title"), 300)
            editorial["zh_summary"] = formatted_summary(provider_review)
            editorial["summary_reason"] = f"已由 {meta['label']} 依目前可讀資料補閱讀建議與摘要。"
        editorial[meta["generated_key"]] = generated_at
        record["editorial_triage"] = editorial
        changed += 1
    return changed


def batched(records: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def item_title(record: dict[str, Any]) -> str:
    return clean_text(record.get("title") or record.get("source_name") or record.get("id"), 120) or "未命名項目"


def status_item_title(records: list[dict[str, Any]]) -> str:
    titles = [item_title(record) for record in records[:3]]
    suffix = f" 等 {len(records)} 筆" if len(records) > 3 else ""
    return "、".join(titles) + suffix


def progress_status(
    args: argparse.Namespace,
    progress: dict[str, int],
    *,
    state: str = "running",
    message: str,
    provider: str = "",
    kind: str = "",
    batch_records: list[dict[str, Any]] | None = None,
    returncode: int | None = None,
) -> None:
    payload: dict[str, Any] = {
        "command": args.status_command,
        "state": state,
        "message": message,
        "index": progress.get("index", 0),
        "total": progress.get("total", 0),
        "provider": provider,
        "kind": kind,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if progress.get("end_index") and progress.get("end_index") != progress.get("index"):
        payload["end_index"] = progress["end_index"]
    if batch_records:
        payload["item_id"] = clean_text(batch_records[0].get("id"))
        payload["item_title"] = status_item_title(batch_records)
    if returncode is not None:
        payload["returncode"] = returncode
    write_status(args.status_file, payload)


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


def process_file(
    path: Path,
    kind: str,
    args: argparse.Namespace,
    progress: dict[str, int] | None = None,
    records: list[dict[str, Any]] | None = None,
    targets: list[dict[str, Any]] | None = None,
) -> tuple[int, int]:
    records = records if records is not None else load_jsonl(path)
    targets = targets if targets is not None else collect_targets(records, args, kind)
    if args.prepare_only or not targets:
        return len(targets), 0
    if progress is None:
        progress = {"index": 0, "end_index": 0, "total": len(targets)}

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
            start_index = progress["index"] + 1
            end_index = progress["index"] + len(batch_records)
            progress["index"] = start_index
            progress["end_index"] = end_index
            label = provider_meta(provider)["label"]
            progress_status(
                args,
                progress,
                message=f"正在用 {label} 補 AI 閱讀建議",
                provider=provider,
                kind=kind,
                batch_records=batch_records,
            )
            batch_input = [review_input(record) for record in batch_records]
            reviews = run_provider(batch_input, args, provider)
            batch_changed = apply_reviews(records, reviews, provider, replace_existing=args.replace_existing)
            changed += batch_changed
            progress["index"] = end_index
            progress["end_index"] = end_index
            if batch_changed and not args.dry_run:
                for record in records:
                    record.pop("_line", None)
                write_jsonl(path, records)
            progress_status(
                args,
                progress,
                message=f"已完成 {progress['index']}/{progress['total']} 筆 AI 閱讀建議",
                provider=provider,
                kind=kind,
                batch_records=batch_records,
            )
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
    parser.add_argument("--replace-existing", action="store_true", help="After a successful run, clear existing model reviews on selected records before writing the new review.")
    parser.add_argument("--prepare-only", action="store_true", help="Only count records that would be sent to the selected AI CLI.")
    parser.add_argument("--dry-run", action="store_true", help="Call the selected AI CLI but do not write JSONL.")
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--status-command", default="codex_enrich_reviews")
    args = parser.parse_args()

    provider_label = (
        "隨機（Codex 35 / Claude 35 / Gemini 15 / Ollama 15，逐筆加權）"
        if args.provider == "random"
        else provider_meta(args.provider)["label"]
    )

    planned: list[tuple[str, Path, str, list[dict[str, Any]], list[dict[str, Any]]]] = []
    if args.target in {"candidates", "both"}:
        records = load_jsonl(args.candidates)
        planned.append(("RSS 新進", args.candidates, "candidates", records, collect_targets(records, args, "candidates")))
    if args.target in {"items", "both"}:
        records = load_jsonl(args.items)
        planned.append(("資料庫項目", args.items, "items", records, collect_targets(records, args, "items")))
    progress = {"index": 0, "end_index": 0, "total": sum(len(entry[4]) for entry in planned)}
    progress_status(
        args,
        progress,
        message=(
            f"準備用 {provider_label} 補 {progress['total']} 筆 AI 閱讀建議"
            if progress["total"]
            else "沒有找到需要補 AI 閱讀建議的項目"
        ),
    )

    totals: list[tuple[str, int, int]] = []
    try:
        for label, path, kind, records, targets in planned:
            totals.append((label, *process_file(path, kind, args, progress, records, targets)))
    except Exception as exc:
        progress_status(args, progress, state="failed", message=f"AI 閱讀建議失敗：{exc}", returncode=1)
        raise

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
    progress_status(
        args,
        progress,
        state="done",
        message=f"AI 閱讀建議完成：已處理 {progress['index']}/{progress['total']} 筆",
        returncode=0,
    )
    print(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
