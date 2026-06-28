#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from page_metadata import infer_language_from_text


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
DEFAULT_OLLAMA_MODEL = "TwinkleAI/gemma-3-4B-T1-it"
AI_PROVIDERS = {
    "codex": {"label": "Codex", "generator": "codex-cli"},
    "claude": {"label": "Claude Code", "generator": "claude-code-cli"},
    "gemini": {"label": "Gemini", "generator": "agy-cli"},
    "ollama": {"label": "Ollama CLI", "generator": "ollama-cli"},
}


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


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


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
    edited = clean_markdown(metadata.get("edited_markdown"), 42000)
    if edited:
        return edited
    markdown = clean_markdown(metadata.get("article_markdown"), 42000)
    if markdown:
        return markdown
    text = clean_text(metadata.get("article_text"), 36000)
    if text:
        title = clean_text(metadata.get("title") or record.get("title"), 320)
        return f"# {title}\n\n{text}" if title else text
    return ""


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
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "codex exec failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
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


def run_ollama(record: dict[str, Any], markdown: str, language: str, timeout: int) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema = output_schema()
    prompt = build_prompt(record, markdown, language, "ollama")
    prompt += f"\n\n請務必只輸出 JSON 物件，且完全符合以下 JSON Schema，不要任何額外說明或 markdown 包裝：\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
    (cache / "ollama-translate-prompt.md").write_text(prompt, encoding="utf-8")
    model = ollama_model()
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
    (cache / "ollama-translate-output.json").write_text(result.stdout, encoding="utf-8")
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
    if provider == "ollama":
        return run_ollama(record, markdown, language, timeout)
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


def build_chunk_prompt(chunk_md: str, language: str, index: int, total: int) -> str:
    return (
        f"你是 Ian Open News 的翻譯編輯。把下面這段{('（' + language + '）') if language else ''}文章片段"
        f"翻成台灣讀者自然可讀的繁體中文。這是全文的第 {index + 1} / {total} 段。\n\n"
        "規則：\n"
        "- 只翻譯這段，保留 Markdown 結構、連結、列表與小標，不要改寫成摘要。\n"
        "- 使用台灣習慣用語與標點；專有名詞第一次出現可保留英文或加括號。\n"
        "- 不要上網、不要補不存在的事實、不要加任何說明或 JSON。\n"
        "- 直接輸出翻譯後的 Markdown 片段。\n\n"
        f"片段：\n{chunk_md}"
    )


def _text_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + str(Path.home() / ".local" / "bin") + ":" + env.get("PATH", "")
    return env


def run_codex_text(prompt: str, timeout: int) -> str:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    output_path = cache / "codex-translate-chunk.txt"
    command = [
        codex_path(), "-a", "never", "exec", "--ephemeral", "--cd", str(ROOT),
        "--sandbox", "read-only", "--color", "never", "--output-last-message", str(output_path), "-",
    ]
    result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=_text_env())
    if result.returncode != 0:
        raise RuntimeError(f"codex exec failed\n{result.stderr[-1500:]}")
    return output_path.read_text(encoding="utf-8")


def run_claude_text(prompt: str, timeout: int) -> str:
    command = [
        claude_path(), "--print", "--input-format", "text", "--output-format", "text",
        "--no-session-persistence", "--permission-mode", "dontAsk", "--tools", "",
    ]
    result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=_text_env())
    if result.returncode != 0:
        raise RuntimeError(f"claude print failed\n{result.stderr[-1500:]}")
    return result.stdout


def run_gemini_text(prompt: str, timeout: int) -> str:
    command = [agy_path(), "--print", prompt]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, env=_text_env())
    if result.returncode != 0:
        raise RuntimeError(f"agy print failed\n{result.stderr[-1500:]}")
    return result.stdout


def run_ollama_text(prompt: str, timeout: int) -> str:
    model = ollama_model()
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
    if provider == "ollama":
        return strip_wrapping(run_ollama_text(prompt, timeout))
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
) -> dict[str, Any]:
    item_id = clean_text(record.get("id"))
    chunks = split_markdown_chunks(markdown, max_chunk_chars)
    total = len(chunks)
    source_hash = hashlib.sha1(markdown.encode("utf-8")).hexdigest()[:16]

    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    metadata = dict(metadata)
    progress = metadata.get("translation_progress") if isinstance(metadata.get("translation_progress"), dict) else {}
    if progress.get("source_hash") != source_hash or not isinstance(progress.get("chunks"), dict):
        progress = {"source_hash": source_hash, "total": total, "chunks": {}}
    done_chunks: dict[str, str] = dict(progress.get("chunks") or {})

    for index in range(total):
        key = str(index)
        if clean_text(done_chunks.get(key)):
            continue
        write_status(status_file, {
            "state": "running", "done": len(done_chunks), "total": total,
            "message": f"翻譯第 {index + 1}/{total} 段中…（{provider_label(provider)}）",
        })
        zh = run_chunk(provider, build_chunk_prompt(chunks[index], language, index, total), timeout)
        if not clean_text(zh):
            raise RuntimeError(f"第 {index + 1}/{total} 段翻譯回傳空白。")
        done_chunks[key] = zh
        # 每段即時寫回，失敗時已完成的段不會白費。
        metadata["translation_progress"] = {"source_hash": source_hash, "total": total, "chunks": done_chunks, "updated_at": now_iso(), "last_provider": provider}
        record["reading_metadata"] = metadata
        if not dry_run:
            write_jsonl(items_path, records)

    zh_markdown = "\n\n".join(done_chunks[str(i)] for i in range(total)).strip()
    payload = {
        "id": item_id,
        "source_language": language,
        "zh_title": zh_title_from_markdown(zh_markdown, item_title(record)),
        "zh_markdown": zh_markdown,
        "note": f"分 {total} 段翻譯（{provider_label(provider)}）。",
    }
    apply_translation(record, payload, language, provider)
    # 完成後清掉逐段暫存，只留完成記號。
    metadata = dict(record.get("reading_metadata") or {})
    metadata["translation_progress"] = {"source_hash": source_hash, "total": total, "done": total, "completed_at": now_iso()}
    record["reading_metadata"] = metadata
    if not dry_run:
        write_jsonl(items_path, records)
    write_status(status_file, {"state": "done", "done": total, "total": total, "message": f"翻譯完成，共 {total} 段。"})
    return payload


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def apply_translation(record: dict[str, Any], payload: dict[str, Any], language: str, provider: str) -> bool:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    metadata = dict(metadata)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    zh_title = clean_text(payload.get("zh_title"), 320)
    zh_markdown = clean_markdown(payload.get("zh_markdown"), 90000)
    source_label = provider_label(provider)
    provider_prefix = provider if provider in {"claude", "gemini", "ollama"} else "codex"
    metadata.update(
        {
            f"{provider_prefix}_translated_zh_title": zh_title,
            f"{provider_prefix}_translated_article_markdown_zh": zh_markdown,
            f"{provider_prefix}_translated_article_markdown_zh_chars": len(zh_markdown),
            f"{provider_prefix}_translation_source": source_label,
            f"{provider_prefix}_translation_generated_at": generated_at,
            f"{provider_prefix}_translation_note": clean_text(payload.get("note"), 600),
        }
    )
    if provider == "codex" or not clean_text(metadata.get("translated_article_markdown_zh")):
        metadata.update(
            {
                "translated_zh_title": zh_title,
                "translated_zh_title_source": source_label,
                "translated_article_markdown_zh": zh_markdown,
                "translated_article_markdown_zh_chars": len(zh_markdown),
                "translation_source": source_label,
                "translation_generated_at": generated_at,
                "translation_note": clean_text(payload.get("note"), 600),
            }
        )
    if language and not clean_text(metadata.get("original_language")):
        metadata["original_language"] = language
        metadata["original_language_source"] = "推斷"
    record["reading_metadata"] = metadata
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Use an AI CLI to translate one fetched article into Taiwan Traditional Chinese.")
    parser.add_argument("--provider", choices=sorted(AI_PROVIDERS), default="codex")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--id", required=True)
    parser.add_argument("--timeout", type=int, default=480, help="每段翻譯的逾時秒數")
    parser.add_argument("--status-file", type=Path, default=None, help="進度寫到這個 JSON，給前端輪詢")
    parser.add_argument("--max-chunk-chars", type=int, default=2400)
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
            args.status_file, args.max_chunk_chars, args.timeout, args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - 失敗時保留已完成的段，並回報進度
        progress = (record.get("reading_metadata") or {}).get("translation_progress") or {}
        done = len(progress.get("chunks") or {}) if isinstance(progress.get("chunks"), dict) else 0
        total = progress.get("total") or 0
        write_status(args.status_file, {"state": "failed", "done": done, "total": total, "message": f"翻譯中斷（已完成 {done}/{total} 段，可再按一次從這裡繼續）：{clean_text(exc, 200)}"})
        raise SystemExit(f"translate failed at {done}/{total}: {exc}")
    total = (record.get("reading_metadata") or {}).get("translation_progress", {}).get("total", 0)
    print(f"translated id={args.id} provider={provider_label(args.provider)} chunks={total} language={language or 'unknown'} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
