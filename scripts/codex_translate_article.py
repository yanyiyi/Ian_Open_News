#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from page_metadata import infer_language_from_text, is_access_prompt_text

try:
    from ai_model_settings import task_model, task_provider
except ImportError:  # Keep the standalone translator usable before settings rollout.
    def task_model(_task: str, _provider: str) -> str:
        return ""

    def task_provider(_task: str) -> str:
        return "codex"


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
PDF_TABLES_DIR = ROOT / "database" / "pdf-tables"
PDF_ARTICLES_DIR = ROOT / "database" / "pdf-articles"
DEFAULT_OLLAMA_MODEL = "TwinkleAI/gemma-3-4B-T1-it"
OLLAMA_MODELS = {
    "ollama": DEFAULT_OLLAMA_MODEL,
    "ollama-gemma4": "gemma4:12b-mlx",
    "ollama-twinkle": "TwinkleAI/gemma-3-4B-T1-it",
}
AI_PROVIDERS = {
    "codex": {"label": "Codex", "generator": "codex-cli"},
    "claude": {"label": "Claude Code", "generator": "claude-code-cli"},
    "gemini": {"label": "Gemini", "generator": "agy-cli"},
    "ollama": {"label": "Ollama CLI", "generator": "ollama-cli"},
    "ollama-gemma4": {"label": "Ollama gemma4:12b MLX", "generator": "ollama-cli", "translation_prefix": "ollama_gemma4"},
    "ollama-twinkle": {"label": "TwinkleAI:Gemma-3-4B-T1-IT", "generator": "ollama-cli", "translation_prefix": "ollama_twinkle"},
}
DEFAULT_CODEX_TRANSLATION_MODEL = "gpt-5.4"


def clean_text(value: object, limit: int | None = None) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    text = "\n".join(line for line in text.split("\n") if line.strip()).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def clean_markdown(value: object, limit: int | None = None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "\n\n..."
    return text


def clean_layout_markdown(value: object, limit: int | None = None) -> str:
    """Normalize Markdown without collapsing fixed-width table columns."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "\n\n..."
    return text


def codex_translation_model() -> str:
    """Model compatible with the standalone CLI used by the local web worker."""
    return clean_text(os.environ.get("IAN_OPEN_NEWS_CODEX_MODEL") or task_model("translation", "codex") or DEFAULT_CODEX_TRANSLATION_MODEL, 80)


def codex_failure_detail(stderr: str, stdout: str = "") -> str:
    combined = f"{stderr}\n{stdout}"
    messages = re.findall(r'"message"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', combined)
    if messages:
        try:
            return json.loads(f'"{messages[-1]}"')
        except json.JSONDecodeError:
            return messages[-1]
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    return lines[-1] if lines else "Codex CLI 未回傳錯誤細節。"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    if path.name in ("items.jsonl", "rejected-items.jsonl"):
        import fulltext_store
        fulltext_store.hydrate_items(records)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if path.name in ("items.jsonl", "rejected-items.jsonl"):
        import fulltext_store
        fulltext_store.dehydrate_items(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_record(path: Path, record: dict[str, Any]) -> None:
    item_id = clean_text(record.get("id"))
    records = load_jsonl(path)
    out: list[dict[str, Any]] = []
    replaced = False
    for row in records:
        if clean_text(row.get("id")) == item_id:
            out.append(record)
            replaced = True
        else:
            out.append(row)
    if replaced:
        write_jsonl(path, out)


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


def provider_label(provider: str) -> str:
    return AI_PROVIDERS.get(provider, AI_PROVIDERS["codex"])["label"]


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


def load_json_from_text(text: str) -> Any:
    raw = prepare_json_candidate(text)
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
            try:
                return json.loads(prepare_json_candidate(candidate))
            except json.JSONDecodeError:
                continue
    raise RuntimeError("model output missing valid JSON payload")


def parse_cli_json(raw: str) -> dict[str, Any]:
    payload = load_json_from_text(raw)
    if isinstance(payload, dict) and "zh_markdown" in payload:
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


def item_title(record: dict[str, Any]) -> str:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    codex_review = editorial.get("codex_review") if isinstance(editorial.get("codex_review"), dict) else {}
    return (
        clean_text(record.get("editorial_title"), 320)
        or clean_text(codex_review.get("zh_title"), 320)
        or clean_text(editorial.get("zh_title"), 320)
        or clean_text(metadata.get("translated_zh_title"), 320)
        or clean_text(metadata.get("title"), 320)
        or clean_text(record.get("title"), 320)
    )


def source_markdown(record: dict[str, Any]) -> str:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    edited = clean_markdown(metadata.get("edited_markdown"), 500000)
    edited_base = clean_text(metadata.get("edited_markdown_base")).casefold()
    item_id = re.sub(r"[^A-Za-z0-9._-]+", "-", clean_text(record.get("id"))).strip("-")
    integrated_path = PDF_ARTICLES_DIR / f"{item_id}.md" if item_id else None
    integrated = (
        clean_layout_markdown(integrated_path.read_text(encoding="utf-8"), 500000)
        if integrated_path and integrated_path.is_file()
        else ""
    )
    if edited and not edited_base.startswith("zh"):
        markdown = edited
    elif integrated:
        markdown = integrated
    else:
        markdown = clean_markdown(metadata.get("article_markdown"), 500000)
    if markdown and not is_access_prompt_text(markdown):
        source = markdown
    else:
        text = clean_text(metadata.get("article_text"), 500000)
        if not text or is_access_prompt_text(text):
            return ""
        title = clean_text(metadata.get("title") or record.get("title"), 320)
        source = f"# {title}\n\n{text}" if title else text
    tables_path = PDF_TABLES_DIR / f"{item_id}.md" if item_id else None
    if not integrated and tables_path and tables_path.is_file():
        tables = clean_layout_markdown(tables_path.read_text(encoding="utf-8"), 150000)
        if tables:
            source = f"{source}\n\n---\n\n{tables}"
    return source


def source_language(record: dict[str, Any], markdown: str) -> str:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    language = clean_text(metadata.get("original_language"))
    if language in {"unknown", "und"}:
        language = ""
    return language or infer_language_from_text(markdown)


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "source_language", "zh_title", "zh_markdown", "note"],
        "properties": {
            "id": {"type": "string"},
            "source_language": {"type": "string"},
            "zh_title": {"type": "string"},
            "zh_markdown": {"type": "string"},
            "note": {"type": "string"},
        },
    }


def build_prompt(record: dict[str, Any], markdown: str, language: str, provider: str = "codex") -> str:
    payload = {
        "id": record.get("id"),
        "title": clean_text(record.get("title"), 320),
        "display_title": item_title(record),
        "url": record.get("url", ""),
        "source_name": record.get("source_name", ""),
        "source_language": language,
        "markdown": markdown,
    }
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"""你是 Ian Open News 的翻譯編輯，請用 {provider_label(provider)} 把下列外語文章翻成台灣讀者自然可讀的繁體中文。

規則：
- 只翻譯提供的 markdown，不要上網，不要補不存在的事實。
- 使用台灣習慣用語與標點。專有名詞第一次出現時可保留英文或加括號，但不要過度意譯。
- 保留 Markdown 結構、連結、列表與小標。不要把整篇改寫成摘要。
- 若原文有明顯廣告、導購、網站導覽或與正文無關的樣板文字，可略過。
- zh_title 請給自然的中文標題；zh_markdown 第一個 H1 也要是中文標題。
- 回覆必須符合 JSON schema，不要輸出 Markdown 之外的說明。

資料：
{data}
"""


def run_codex(record: dict[str, Any], markdown: str, language: str, timeout: int) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema_path = cache / "codex-translate.schema.json"
    output_path = cache / "codex-translate-output.json"
    prompt_path = cache / "codex-translate-prompt.md"
    schema_path.write_text(json.dumps(output_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = build_prompt(record, markdown, language, "codex")
    prompt_path.write_text(prompt, encoding="utf-8")
    output_path.unlink(missing_ok=True)

    command = [
        codex_path(),
        "-m",
        codex_translation_model(),
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
    env = _codex_env()
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "codex exec failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    if not output_path.is_file():
        raise RuntimeError(
            "Codex completed without writing translation output\n"
            f"STDOUT:\n{result.stdout[-1500:]}\nSTDERR:\n{result.stderr[-1500:]}"
        )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    if clean_text(payload.get("id")) != clean_text(record.get("id")):
        raise RuntimeError("Codex output id mismatch")
    if not clean_text(payload.get("zh_markdown")):
        raise RuntimeError("Codex output missing zh_markdown")
    return payload


def run_claude(record: dict[str, Any], markdown: str, language: str, timeout: int) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(record, markdown, language, "claude")
    (cache / "claude-translate-prompt.md").write_text(prompt, encoding="utf-8")
    command = [
        claude_path(),
        "--print",
        "--input-format",
        "text",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False),
    ]
    model = task_model("translation", "claude")
    if model:
        command += ["--model", model]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "claude print failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    (cache / "claude-translate-output.json").write_text(result.stdout, encoding="utf-8")
    payload = parse_cli_json(result.stdout)
    if clean_text(payload.get("id")) != clean_text(record.get("id")):
        raise RuntimeError("Claude output id mismatch")
    if not clean_text(payload.get("zh_markdown")):
        raise RuntimeError("Claude output missing zh_markdown")
    return payload


def run_gemini(record: dict[str, Any], markdown: str, language: str, timeout: int) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(record, markdown, language, "gemini")
    prompt += f"\n\n請務必輸出 JSON 格式，並完全符合以下 JSON Schema：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    (cache / "gemini-translate-prompt.md").write_text(prompt, encoding="utf-8")
    command = [
        agy_path(),
        "--print",
        prompt,
    ]
    model = task_model("translation", "gemini")
    if model:
        command += ["--model", model]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "agy print failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    (cache / "gemini-translate-output.json").write_text(result.stdout, encoding="utf-8")
    payload = parse_cli_json(result.stdout)
    if clean_text(payload.get("id")) != clean_text(record.get("id")):
        raise RuntimeError("Gemini output id mismatch")
    if not clean_text(payload.get("zh_markdown")):
        raise RuntimeError("Gemini output missing zh_markdown")
    return payload


def run_ollama(record: dict[str, Any], markdown: str, language: str, timeout: int, provider: str = "ollama") -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(record, markdown, language, provider)
    prompt += f"\n\n請務必只輸出 JSON 物件，且完全符合以下 JSON Schema，不要任何額外說明或 markdown 包裝：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    safe_provider = re.sub(r"[^a-z0-9_-]+", "-", provider.lower())
    (cache / f"{safe_provider}-translate-prompt.md").write_text(prompt, encoding="utf-8")
    model = task_model("translation", provider) or ollama_model(provider)
    command = [
        ollama_path(),
        "run",
        model,
        "--format",
        "json",
        "--nowordwrap",
        "--hidethinking",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=_text_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ollama run failed（model: {model}）\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    (cache / f"{safe_provider}-translate-output.json").write_text(result.stdout, encoding="utf-8")
    payload = parse_cli_json(result.stdout)
    if clean_text(payload.get("id")) != clean_text(record.get("id")):
        raise RuntimeError("Ollama output id mismatch")
    if not clean_text(payload.get("zh_markdown")):
        raise RuntimeError("Ollama output missing zh_markdown")
    return payload


def run_provider(record: dict[str, Any], markdown: str, language: str, provider: str, timeout: int) -> dict[str, Any]:
    if provider == "claude":
        return run_claude(record, markdown, language, timeout)
    if provider == "gemini":
        return run_gemini(record, markdown, language, timeout)
    if provider.startswith("ollama"):
        return run_ollama(record, markdown, language, timeout, provider)
    return run_codex(record, markdown, language, timeout)


def _sentence_split(text: str, max_chars: int) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+", text)
    out: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if current and len(current) + len(part) + 1 > max_chars:
            out.append(current)
            current = part
        else:
            current = f"{current} {part}" if current else part
    if current:
        out.append(current)
    return out or [text]


def split_markdown_chunks(markdown: str, max_chars: int = 2400) -> list[str]:
    """把全文切成接近 max_chars 的段。先用 Markdown 空行分段；過長才退用單行與句子。"""
    units: list[str] = []
    for block in re.split(r"\n\s*\n", markdown):
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_chars:
            units.append(block)
            continue
        for line in block.split("\n"):
            line = line.strip()
            if not line:
                continue
            if len(line) <= max_chars:
                units.append(line)
            else:
                units.extend(_sentence_split(line, max_chars))
    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) + 2 > max_chars:
            chunks.append(current)
            current = unit
        else:
            current = f"{current}\n\n{unit}" if current else unit
    if current:
        chunks.append(current)
    return chunks or [markdown.strip()]


def strip_wrapping(text: str) -> str:
    text = (text or "").strip()
    fence = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    return text


TABLE_CELL_MARKER = "[[[IAN_TABLE_CELL]]]"
TABLE_CONTINUED_MARKER = "[[[IAN_TABLE_CONTINUED]]]"


def protect_layout_tokens(markdown: str) -> str:
    """Protect structural TSV tokens that language models tend to normalize."""

    def protect_fence(match: re.Match[str]) -> str:
        body = match.group(2)
        body = body.replace("\t", TABLE_CELL_MARKER)
        body = body.replace("[continued]", TABLE_CONTINUED_MARKER)
        return f"{match.group(1)}{body}{match.group(3)}"

    return re.sub(
        r"(```tsv[^\n]*\n)(.*?)(\n```)",
        protect_fence,
        markdown,
        flags=re.I | re.S,
    )


def restore_layout_tokens(markdown: str) -> str:
    """Restore protected tokens after translation, tolerating added spaces."""
    restored = re.sub(
        r"[ \t]*\[\[\[IAN_TABLE_CELL\]\]\][ \t]*",
        "\t",
        markdown,
        flags=re.I,
    )
    return re.sub(
        r"\[\[\[IAN_TABLE_CONTINUED\]\]\]",
        "[continued]",
        restored,
        flags=re.I,
    )


def layout_signature(markdown: str) -> tuple[int, int, int]:
    """Return structural counts used to reject flattened table translations."""
    return (
        len(re.findall(r"```tsv\b", markdown, flags=re.I)),
        markdown.count("\t"),
        markdown.count("[continued]"),
    )


def validate_translated_layout(source: str, translated: str) -> None:
    expected = layout_signature(source)
    if expected[0] and layout_signature(translated) != expected:
        actual = layout_signature(translated)
        raise RuntimeError(
            "表格結構驗證失敗："
            f"預期 TSV/Tab/續表為 {expected[0]}/{expected[1]}/{expected[2]}，"
            f"實際為 {actual[0]}/{actual[1]}/{actual[2]}。"
        )


def tsv_fences(markdown: str) -> list[str]:
    return re.findall(r"```tsv[^\n]*\n.*?\n```", markdown, flags=re.I | re.S)


def replace_tsv_fences(markdown: str, replacements: list[str]) -> str:
    replacement_iter = iter(replacements)
    replaced = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal replaced
        try:
            value = next(replacement_iter)
        except StopIteration as exc:
            raise RuntimeError("修復後表格數量少於既有翻譯。") from exc
        replaced += 1
        return value

    result = re.sub(r"```tsv[^\n]*\n.*?\n```", replace, markdown, flags=re.I | re.S)
    if replaced != len(replacements):
        raise RuntimeError(f"既有翻譯有 {replaced} 張表，但修復結果有 {len(replacements)} 張。")
    try:
        next(replacement_iter)
    except StopIteration:
        return result
    raise RuntimeError("修復後表格數量多於既有翻譯。")


def split_tsv_fence_batches(fence: str, max_body_lines: int = 24) -> list[str]:
    lines = fence.splitlines()
    if len(lines) < 3 or not re.match(r"^```tsv\b", lines[0], flags=re.I) or lines[-1].strip() != "```":
        raise RuntimeError("無法切分不完整的 TSV fence。")
    body = lines[1:-1]
    return [
        "```tsv\n" + "\n".join(body[start : start + max_body_lines]) + "\n```"
        for start in range(0, len(body), max_body_lines)
    ] or ["```tsv\n\n```"]


def translate_tsv_group(
    table_group: str,
    language: str,
    provider: str,
    group_index: int,
    group_total: int,
    timeout: int,
) -> str:
    """Translate long tables in row-safe batches, then rebuild original fences."""

    def translate_batch(batch: str, batch_label: str) -> str:
        prompt = build_chunk_prompt(
            protect_layout_tokens(batch), language, group_index, group_total
        ) + (
            f"\n\n這是本表格的{batch_label}。"
            "必須輸出這一批的每一列，且只輸出一個完整的 ```tsv fence。"
        )
        try:
            translated = restore_layout_tokens(run_chunk(provider, prompt, timeout))
            translated_parts = tsv_fences(translated)
            if len(translated_parts) != 1:
                raise RuntimeError(
                    f"表格第 {group_index + 1}/{group_total} 段的{batch_label}"
                    "未回傳一個 TSV fence。"
                )
            validate_translated_layout(batch, translated_parts[0])
            return translated_parts[0]
        except RuntimeError as exc:
            body = batch.splitlines()[1:-1]
            if len(body) <= 1 or "表格" not in str(exc):
                raise
            midpoint = len(body) // 2
            halves = [body[:midpoint], body[midpoint:]]
            translated_halves = [
                translate_batch(
                    "```tsv\n" + "\n".join(lines) + "\n```",
                    f"{batch_label}（自動二分 {part_index + 1}/2）",
                )
                for part_index, lines in enumerate(halves)
            ]
            combined_body: list[str] = []
            for translated_half in translated_halves:
                combined_body.extend(translated_half.splitlines()[1:-1])
            combined = "```tsv\n" + "\n".join(combined_body) + "\n```"
            validate_translated_layout(batch, combined)
            return combined

    translated_fences: list[str] = []
    for fence in tsv_fences(table_group):
        batches = split_tsv_fence_batches(fence)
        translated_bodies: list[str] = []
        for batch_index, batch in enumerate(batches):
            translated = translate_batch(
                batch,
                f"第 {batch_index + 1}/{len(batches)} 批列",
            )
            translated_bodies.extend(translated.splitlines()[1:-1])
        translated_fences.append("```tsv\n" + "\n".join(translated_bodies) + "\n```")
    translated_group = "\n\n".join(translated_fences)
    validate_translated_layout(table_group, translated_group)
    return translated_group


def translation_prefix(provider: str) -> str:
    return AI_PROVIDERS.get(provider, {}).get("translation_prefix") or (
        provider if provider in {"claude", "gemini", "ollama"} else "codex"
    )


def build_chunk_prompt(chunk_md: str, language: str, index: int, total: int) -> str:
    return (
        f"你是 Ian Open News 的翻譯編輯。把下面這段{('（' + language + '）') if language else ''}文章片段"
        f"翻成台灣讀者自然可讀的繁體中文。這是全文的第 {index + 1} / {total} 段。\n\n"
        "規則：\n"
        "- 只翻譯這段，保留 Markdown 結構、連結、列表與小標，不要改寫成摘要。\n"
        "- 使用台灣習慣用語與標點；專有名詞第一次出現可保留英文或加括號。\n"
        "- 若片段含有 ```tsv 表格，保留 fence、Tab 分欄與每一列；只翻譯儲存格文字。\n"
        f"- 若片段含有 {TABLE_CELL_MARKER} 或 {TABLE_CONTINUED_MARKER}，必須逐字保留每一個標記，不能翻譯、刪除、移動或改寫。\n"
        "- 不要上網、不要補不存在的事實、不要加任何說明或 JSON。\n"
        "- 直接輸出翻譯後的 Markdown 片段。\n\n"
        f"片段：\n{chunk_md}"
    )


def _text_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + str(Path.home() / ".local" / "bin") + ":" + env.get("PATH", "")
    return env


def _codex_env() -> dict[str, str]:
    """Give background Codex CLI calls a writable state directory.

    The desktop-launched local web service can read the user's Codex config but
    may not be allowed to update ~/.codex/state_*.sqlite.  Keep ephemeral CLI
    state under this repo's gitignored cache and seed only auth/config files.
    """
    env = _text_env()
    source_home = Path(env.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    runtime_home = ROOT / ".cache" / "codex-cli-home"
    runtime_home.mkdir(parents=True, exist_ok=True)
    if source_home.resolve() != runtime_home.resolve():
        for filename in ("auth.json", "config.toml"):
            source = source_home / filename
            target = runtime_home / filename
            if not source.is_file():
                continue
            if not target.exists() or source.stat().st_mtime_ns > target.stat().st_mtime_ns:
                shutil.copy2(source, target)
    env["CODEX_HOME"] = str(runtime_home)
    return env


def run_codex_text(prompt: str, timeout: int) -> str:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    # Every CLI call needs its own output path. Translation requests can run in
    # parallel from multiple item pages; a shared file lets one item consume
    # another item's last message.
    output_path = cache / f"codex-translate-{os.getpid()}-{uuid.uuid4().hex}.txt"
    command = [
        codex_path(), "-m", codex_translation_model(), "-a", "never", "exec", "--ephemeral", "--cd", str(ROOT),
        "--sandbox", "read-only", "--color", "never", "--output-last-message", str(output_path), "-",
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=_codex_env())
        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI 失敗：{codex_failure_detail(result.stderr, result.stdout)}")
        if not output_path.is_file():
            stdout_tables = tsv_fences(result.stdout)
            if stdout_tables:
                return "\n\n".join(stdout_tables)
            raise RuntimeError(
                "Codex completed without writing translation output\n"
                f"{result.stderr[-1500:] or result.stdout[-1500:]}"
            )
        output = output_path.read_text(encoding="utf-8")
        if not clean_text(output):
            raise RuntimeError("Codex wrote an empty translation output")
        return output
    finally:
        output_path.unlink(missing_ok=True)


def run_claude_text(prompt: str, timeout: int) -> str:
    command = [
        claude_path(), "--print", "--input-format", "text", "--output-format", "text",
        "--no-session-persistence", "--permission-mode", "dontAsk", "--tools", "",
    ]
    model = task_model("translation", "claude")
    if model:
        command += ["--model", model]
    result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=_text_env())
    if result.returncode != 0:
        raise RuntimeError(f"claude print failed\n{result.stderr[-1500:]}")
    return result.stdout


def run_gemini_text(prompt: str, timeout: int) -> str:
    command = [agy_path(), "--print", prompt]
    model = task_model("translation", "gemini")
    if model:
        command += ["--model", model]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, env=_text_env())
    if result.returncode != 0:
        raise RuntimeError(f"agy print failed\n{result.stderr[-1500:]}")
    return result.stdout


def run_ollama_text(prompt: str, timeout: int, provider: str = "ollama") -> str:
    model = task_model("translation", provider) or ollama_model(provider)
    command = [ollama_path(), "run", model, "--nowordwrap", "--hidethinking"]
    result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=_text_env())
    if result.returncode != 0:
        raise RuntimeError(f"ollama run failed（model: {model}）\n{result.stderr[-1500:] or result.stdout[-1500:]}")
    return result.stdout


def run_chunk(provider: str, prompt: str, timeout: int) -> str:
    if provider == "claude":
        return strip_wrapping(run_claude_text(prompt, timeout))
    if provider == "gemini":
        return strip_wrapping(run_gemini_text(prompt, timeout))
    if provider.startswith("ollama"):
        return strip_wrapping(run_ollama_text(prompt, timeout, provider))
    return strip_wrapping(run_codex_text(prompt, timeout))


def write_status(status_file: Path | None, payload: dict[str, Any]) -> None:
    if not status_file:
        return
    try:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def zh_title_from_markdown(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^\s{0,3}#\s+(.+?)\s*$", line)
        if match:
            return clean_text(match.group(1), 320)
    return clean_text(fallback, 320)


def repair_completed_translation_tables(
    record: dict[str, Any],
    source_chunks: list[str],
    existing_translation: str,
    source_hash: str,
    language: str,
    provider: str,
    items_path: Path,
    status_file: Path | None,
    timeout: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Retranslate only TSV fences when a completed translation flattened them."""
    item_id = clean_text(record.get("id"))
    table_groups = ["\n\n".join(tsv_fences(chunk)) for chunk in source_chunks if tsv_fences(chunk)]
    total = len(table_groups)
    metadata = dict(record.get("reading_metadata") or {})
    progress = metadata.get("translation_table_repair_progress")
    if not isinstance(progress, dict) or progress.get("source_hash") != source_hash:
        progress = {"source_hash": source_hash, "total": total, "chunks": {}}
    done_chunks = dict(progress.get("chunks") or {})
    for key in list(done_chunks):
        try:
            index = int(key)
            validate_translated_layout(table_groups[index], done_chunks[key])
        except (IndexError, TypeError, ValueError, RuntimeError):
            done_chunks.pop(key, None)

    metadata["translation_table_repair_progress"] = {
        "source_hash": source_hash,
        "total": total,
        "chunks": done_chunks,
        "updated_at": now_iso(),
        "last_provider": provider,
    }
    record["reading_metadata"] = metadata
    if not dry_run:
        write_record(items_path, record)

    for index, table_group in enumerate(table_groups):
        key = str(index)
        if clean_text(done_chunks.get(key)):
            continue
        write_status(
            status_file,
            {
                "item_id": item_id,
                "provider": provider,
                "state": "running",
                "done": len(done_chunks),
                "total": total,
                "message": f"修復翻譯表格第 {index + 1}/{total} 段中…（{provider_label(provider)}）",
            },
        )
        translated = translate_tsv_group(
            table_group, language, provider, index, total, timeout
        )
        validate_translated_layout(table_group, translated)
        done_chunks[key] = translated
        metadata["translation_table_repair_progress"] = {
            "source_hash": source_hash,
            "total": total,
            "chunks": done_chunks,
            "updated_at": now_iso(),
            "last_provider": provider,
        }
        record["reading_metadata"] = metadata
        if not dry_run:
            write_record(items_path, record)

    repaired_fences: list[str] = []
    for index in range(total):
        repaired_fences.extend(tsv_fences(done_chunks[str(index)]))
    repaired_markdown = replace_tsv_fences(existing_translation, repaired_fences)
    validate_translated_layout("\n\n".join(table_groups), repaired_markdown)
    payload = {
        "id": item_id,
        "source_language": language,
        "zh_title": zh_title_from_markdown(repaired_markdown, item_title(record)),
        "zh_markdown": repaired_markdown,
        "note": f"保留既有全文翻譯，另修復 {total} 個含表格段落（{provider_label(provider)}）。",
    }
    apply_translation(record, payload, language, provider, source_hash=source_hash)
    metadata = dict(record.get("reading_metadata") or {})
    metadata.pop("translation_table_repair_progress", None)
    metadata["translation_progress"] = {
        "source_hash": source_hash,
        "total": len(source_chunks),
        "done": len(source_chunks),
        "completed_at": now_iso(),
    }
    record["reading_metadata"] = metadata
    if not dry_run:
        write_record(items_path, record)
    write_status(
        status_file,
        {
            "item_id": item_id,
            "provider": provider,
            "state": "done",
            "done": total,
            "total": total,
            "message": f"翻譯表格修復完成，共 {total} 段。",
        },
    )
    return payload


def translate_record_chunked(
    records: list[dict[str, Any]],
    record: dict[str, Any],
    markdown: str,
    language: str,
    provider: str,
    items_path: Path,
    status_file: Path | None,
    max_chunk_chars: int,
    timeout: int,
    dry_run: bool,
    force: bool = False,
) -> dict[str, Any]:
    item_id = clean_text(record.get("id"))
    chunks = split_markdown_chunks(markdown, max_chunk_chars)
    total = len(chunks)
    source_hash = hashlib.sha1(markdown.encode("utf-8")).hexdigest()[:16]

    def translation_status(**payload: Any) -> dict[str, Any]:
        return {"item_id": item_id, "provider": provider, **payload}

    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    metadata = dict(metadata)
    progress = metadata.get("translation_progress") if isinstance(metadata.get("translation_progress"), dict) else {}
    prefix = translation_prefix(provider)
    existing_translation = clean_layout_markdown(
        metadata.get(f"{prefix}_translated_article_markdown_zh"), 90000
    )
    existing_hash = clean_text(metadata.get(f"{prefix}_translation_source_hash"), 80)
    source_layout = layout_signature(markdown)
    existing_layout = layout_signature(existing_translation)
    if (
        not force
        and existing_translation
        and existing_hash == source_hash
        and source_layout[0] > 0
        and existing_layout[0] == source_layout[0]
        and existing_layout != source_layout
    ):
        return repair_completed_translation_tables(
            record, chunks, existing_translation, source_hash, language, provider,
            items_path, status_file, timeout, dry_run,
        )
    if force or progress.get("source_hash") != source_hash or not isinstance(progress.get("chunks"), dict):
        progress = {"source_hash": source_hash, "total": total, "chunks": {}}
    done_chunks: dict[str, str] = dict(progress.get("chunks") or {})
    # Older translations may have retained the TSV fences while flattening all
    # tab delimiters.  Keep valid prose chunks and invalidate only table chunks
    # whose structural signature no longer matches their source.
    for key in list(done_chunks):
        try:
            chunk_index = int(key)
        except (TypeError, ValueError):
            done_chunks.pop(key, None)
            continue
        if chunk_index < 0 or chunk_index >= total:
            done_chunks.pop(key, None)
            continue
        if layout_signature(chunks[chunk_index])[0]:
            try:
                validate_translated_layout(chunks[chunk_index], done_chunks[key])
            except RuntimeError:
                done_chunks.pop(key, None)
    # Persist the plan before invoking the first provider call.  If the CLI
    # cannot even start, the UI should still report 0/N rather than 0/0 and a
    # retry should retain the correct source hash/chunk plan.
    metadata["translation_progress"] = {
        "source_hash": source_hash,
        "total": total,
        "chunks": done_chunks,
        "updated_at": now_iso(),
        "last_provider": provider,
    }
    record["reading_metadata"] = metadata
    if not dry_run:
        write_record(items_path, record)

    for index in range(total):
        key = str(index)
        if clean_text(done_chunks.get(key)):
            continue
        write_status(
            status_file,
            translation_status(
                state="running",
                done=len(done_chunks),
                total=total,
                message=f"翻譯第 {index + 1}/{total} 段中…（{provider_label(provider)}）",
            ),
        )
        protected_chunk = protect_layout_tokens(chunks[index])
        zh = restore_layout_tokens(
            run_chunk(provider, build_chunk_prompt(protected_chunk, language, index, total), timeout)
        )
        if not clean_text(zh):
            raise RuntimeError(f"第 {index + 1}/{total} 段翻譯回傳空白。")
        validate_translated_layout(chunks[index], zh)
        done_chunks[key] = zh
        # 每段即時寫回，失敗時已完成的段不會白費。
        metadata["translation_progress"] = {"source_hash": source_hash, "total": total, "chunks": done_chunks, "updated_at": now_iso(), "last_provider": provider}
        record["reading_metadata"] = metadata
        if not dry_run:
            write_record(items_path, record)

    zh_markdown = "\n\n".join(done_chunks[str(i)] for i in range(total)).strip()
    payload = {
        "id": item_id,
        "source_language": language,
        "zh_title": zh_title_from_markdown(zh_markdown, item_title(record)),
        "zh_markdown": zh_markdown,
        "note": f"分 {total} 段翻譯（{provider_label(provider)}）。",
    }
    apply_translation(record, payload, language, provider, source_hash=source_hash)
    # 完成後清掉逐段暫存，只留完成記號。
    metadata = dict(record.get("reading_metadata") or {})
    metadata["translation_progress"] = {"source_hash": source_hash, "total": total, "done": total, "completed_at": now_iso()}
    record["reading_metadata"] = metadata
    if not dry_run:
        write_record(items_path, record)
    write_status(
        status_file,
        translation_status(
            state="done",
            done=total,
            total=total,
            message=f"翻譯完成，共 {total} 段。",
        ),
    )
    return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def infer_translation_provider_from_source(source: object) -> str:
    text = clean_text(source, 240).casefold()
    if not text:
        return ""
    provider_signals = [
        ("ollama-twinkle", ("twinkleai", "twinkle", "gemma-3-4b-t1", "gemma-3-4b")),
        ("ollama-gemma4", ("gemma4", "gemma4:12b", "12b-mlx")),
        ("claude", ("claude",)),
        ("gemini", ("gemini",)),
        ("codex", ("codex",)),
    ]
    for provider_name, signals in provider_signals:
        if any(signal in text for signal in signals):
            return provider_name
    return ""


def legacy_translation_provider(metadata: dict[str, Any]) -> str:
    return (
        infer_translation_provider_from_source(metadata.get("translation_source"))
        or infer_translation_provider_from_source(metadata.get("translated_zh_title_source"))
        or "codex"
    )


def apply_translation(
    record: dict[str, Any],
    payload: dict[str, Any],
    language: str,
    provider: str,
    source_hash: str = "",
) -> bool:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    metadata = dict(metadata)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    zh_title = clean_text(payload.get("zh_title"), 320)
    zh_markdown = clean_layout_markdown(payload.get("zh_markdown"), 90000)
    source_label = provider_label(provider)
    provider_prefix = translation_prefix(provider)
    metadata.update(
        {
            f"{provider_prefix}_translated_zh_title": zh_title,
            f"{provider_prefix}_translated_article_markdown_zh": zh_markdown,
            f"{provider_prefix}_translated_article_markdown_zh_chars": len(zh_markdown),
            f"{provider_prefix}_translation_source": source_label,
            f"{provider_prefix}_translation_generated_at": generated_at,
            f"{provider_prefix}_translation_note": clean_text(payload.get("note"), 600),
            f"{provider_prefix}_translation_source_hash": clean_text(source_hash, 80),
        }
    )
    should_update_primary = (
        provider == "codex"
        or not clean_text(metadata.get("translated_article_markdown_zh"))
        or provider == legacy_translation_provider(metadata)
    )
    if should_update_primary:
        metadata.update(
            {
                "translated_zh_title": zh_title,
                "translated_zh_title_source": source_label,
                "translated_article_markdown_zh": zh_markdown,
                "translated_article_markdown_zh_chars": len(zh_markdown),
                "translation_source": source_label,
                "translation_generated_at": generated_at,
                "translation_note": clean_text(payload.get("note"), 600),
                "translation_source_hash": clean_text(source_hash, 80),
            }
        )
    if language and not clean_text(metadata.get("original_language")):
        metadata["original_language"] = language
        metadata["original_language_source"] = "推斷"
    record["reading_metadata"] = metadata
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Use an AI CLI to translate one fetched article into Taiwan Traditional Chinese.")
    parser.add_argument("--provider", choices=sorted(AI_PROVIDERS), default=task_provider("translation"))
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--id", required=True)
    parser.add_argument("--timeout", type=int, default=480, help="每段翻譯的逾時秒數")
    parser.add_argument("--status-file", type=Path, default=None, help="進度寫到這個 JSON，給前端輪詢")
    parser.add_argument("--max-chunk-chars", type=int, default=2400)
    parser.add_argument("--force", action="store_true", help="丟掉既有逐段暫存，從目前全文重新翻譯")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    records = load_jsonl(args.items)
    record = next((item for item in records if clean_text(item.get("id")) == args.id), None)
    if not record:
        write_status(args.status_file, {"state": "failed", "message": f"找不到項目：{args.id}"})
        raise SystemExit(f"找不到項目：{args.id}")
    markdown = source_markdown(record)
    if not markdown:
        write_status(args.status_file, {"state": "failed", "message": "還沒有可翻譯的全文，請先展開全文。"})
        raise SystemExit("這篇還沒有可翻譯的 Markdown 全文，請先展開全文。")
    language = source_language(record, markdown)
    if language.startswith("zh"):
        write_status(args.status_file, {"state": "failed", "message": "這篇看起來已是中文，不需要翻譯。"})
        raise SystemExit("這篇看起來已是中文，不需要自動翻譯。")
    try:
        payload = translate_record_chunked(
            records, record, markdown, language, args.provider, args.items,
            args.status_file, args.max_chunk_chars, args.timeout, args.dry_run, args.force,
        )
    except Exception as exc:  # noqa: BLE001 - 失敗時保留已完成的段，並回報進度
        metadata = record.get("reading_metadata") or {}
        repair_progress = metadata.get("translation_table_repair_progress") or {}
        progress = repair_progress or metadata.get("translation_progress") or {}
        done = len(progress.get("chunks") or {}) if isinstance(progress.get("chunks"), dict) else 0
        total = progress.get("total") or 0
        action = "表格修復" if repair_progress else "翻譯"
        write_status(args.status_file, {"state": "failed", "done": done, "total": total, "message": f"{action}中斷（已完成 {done}/{total} 段，可再按一次從這裡繼續）：{clean_text(exc, 200)}"})
        raise SystemExit(f"translate failed at {done}/{total}: {exc}")
    total = (record.get("reading_metadata") or {}).get("translation_progress", {}).get("total", 0)
    print(f"translated id={args.id} provider={provider_label(args.provider)} chunks={total} language={language or 'unknown'} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
