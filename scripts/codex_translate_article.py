#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from page_metadata import infer_language_from_text


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"


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
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def codex_path() -> str:
    candidate = shutil.which("codex")
    if candidate:
        return candidate
    for path in ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"]:
        if Path(path).exists():
            return path
    raise RuntimeError("找不到 codex CLI，請先確認 /opt/homebrew/bin/codex 是否可用。")


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
    markdown = clean_text(metadata.get("article_markdown"), 42000)
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


def build_prompt(record: dict[str, Any], markdown: str, language: str) -> str:
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
    return f"""你是 Ian Open News 的翻譯編輯，請把下列外語文章翻成台灣讀者自然可讀的繁體中文。

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
    prompt = build_prompt(record, markdown, language)
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


def apply_translation(record: dict[str, Any], payload: dict[str, Any], language: str) -> bool:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    metadata = dict(metadata)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    zh_title = clean_text(payload.get("zh_title"), 320)
    zh_markdown = clean_text(payload.get("zh_markdown"), 90000)
    metadata.update(
        {
            "translated_zh_title": zh_title,
            "translated_zh_title_source": "Codex",
            "translated_article_markdown_zh": zh_markdown,
            "translated_article_markdown_zh_chars": len(zh_markdown),
            "translation_source": "Codex",
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
    parser = argparse.ArgumentParser(description="Use Codex CLI to translate one fetched article into Taiwan Traditional Chinese.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--id", required=True)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    records = load_jsonl(args.items)
    record = next((item for item in records if clean_text(item.get("id")) == args.id), None)
    if not record:
        raise SystemExit(f"找不到項目：{args.id}")
    markdown = source_markdown(record)
    if not markdown:
        raise SystemExit("這篇還沒有可翻譯的 Markdown 全文，請先展開全文。")
    language = source_language(record, markdown)
    if language.startswith("zh"):
        raise SystemExit("這篇看起來已是中文，不需要自動翻譯。")
    payload = run_codex(record, markdown, language, args.timeout)
    apply_translation(record, payload, language)
    if not args.dry_run:
        write_jsonl(args.items, records)
    print(f"translated id={args.id} language={language or 'unknown'} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
