#!/usr/bin/env python3
"""Backfill blank-line paragraph separators for previously fetched Markdown.

The first article-to-Markdown pass wrote one newline between extracted blocks.
That is readable as plain text, but Markdown treats it as a soft line break
inside the same paragraph.  This script keeps list/table/quote/code blocks
together while separating generated prose blocks with blank lines.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITEMS = ROOT / "database" / "items.jsonl"

ARTICLE_METHODS = {"semantic-block", "all-paragraphs", "jsonld.articleBody"}
ARTICLE_MARKDOWN_KEY = "article_markdown"
TRANSLATED_MARKDOWN_KEYS = (
    "translated_article_markdown_zh",
    "codex_translated_article_markdown_zh",
    "claude_translated_article_markdown_zh",
    "gemini_translated_article_markdown_zh",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def markdown_break_counts(markdown: str) -> tuple[int, int]:
    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    blank_breaks = len(re.findall(r"\n[ \t]*\n", text))
    single_breaks = len(re.findall(r"(?<!\n)\n(?!\n)", text))
    return blank_breaks, single_breaks


def needs_paragraph_normalization(markdown: object, min_single_breaks: int = 5) -> bool:
    if not isinstance(markdown, str) or not markdown.strip():
        return False
    blank_breaks, single_breaks = markdown_break_counts(markdown)
    return blank_breaks == 0 and single_breaks >= min_single_breaks


def _is_fence(line: str) -> bool:
    return bool(re.match(r"^\s*(```|~~~)", line))


def _is_table_separator(line: str) -> bool:
    return bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", line))


def _line_kind(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "blank"
    if re.match(r"^#{1,6}\s+", stripped):
        return "heading"
    if re.match(r"^(?:[-*+]|\d+[.)])\s+", stripped):
        return "list"
    if stripped.startswith(">"):
        return "quote"
    if _is_table_separator(stripped) or (stripped.startswith("|") and stripped.endswith("|")):
        return "table"
    if re.match(r"^[-*_]{3,}$", stripped):
        return "thematic"
    if re.match(r"^!\[[^\]]*]\([^)]+\)$", stripped):
        return "media"
    return "paragraph"


def _same_block(previous_kind: str, next_kind: str) -> bool:
    if previous_kind == next_kind and previous_kind in {"list", "quote", "table"}:
        return True
    return False


def normalize_flat_markdown(markdown: str) -> str:
    """Convert a flat one-newline-per-block Markdown string into block Markdown."""
    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    raw_lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]

    blocks: list[tuple[str, list[str]]] = []
    current_kind = ""
    current_lines: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal current_kind, current_lines
        if current_lines:
            blocks.append((current_kind or "paragraph", current_lines))
            current_kind = ""
            current_lines = []

    for line in raw_lines:
        if not line:
            flush()
            continue

        if _is_fence(line):
            if in_fence:
                current_lines.append(line)
                flush()
                in_fence = False
            else:
                flush()
                current_kind = "code"
                current_lines = [line]
                in_fence = True
            continue

        if in_fence:
            current_lines.append(line)
            continue

        kind = _line_kind(line)
        if not current_lines:
            current_kind = kind
            current_lines = [line]
            continue
        if _same_block(current_kind, kind):
            current_lines.append(line)
            continue
        flush()
        current_kind = kind
        current_lines = [line]

    flush()
    return "\n\n".join("\n".join(lines) for _, lines in blocks).strip()


def normalize_markdown_field(
    metadata: dict[str, Any],
    key: str,
    *,
    min_single_breaks: int,
) -> bool:
    value = metadata.get(key)
    if not needs_paragraph_normalization(value, min_single_breaks=min_single_breaks):
        return False
    normalized = normalize_flat_markdown(str(value))
    if normalized == value:
        return False
    metadata[key] = normalized
    chars_key = f"{key}_chars"
    if chars_key in metadata:
        metadata[chars_key] = len(normalized)
    return True


def normalize_item(
    record: dict[str, Any],
    *,
    min_single_breaks: int = 5,
    include_pdf: bool = False,
) -> Counter[str]:
    metadata = record.get("reading_metadata")
    if not isinstance(metadata, dict):
        return Counter()

    changed: Counter[str] = Counter()
    method = str(metadata.get("article_markdown_method") or "")
    if method in ARTICLE_METHODS or (include_pdf and method.startswith("pdf-")):
        if normalize_markdown_field(metadata, ARTICLE_MARKDOWN_KEY, min_single_breaks=min_single_breaks):
            changed[ARTICLE_MARKDOWN_KEY] += 1

    for key in TRANSLATED_MARKDOWN_KEYS:
        if normalize_markdown_field(metadata, key, min_single_breaks=min_single_breaks):
            changed[key] += 1

    return changed


def normalize_records(
    records: list[dict[str, Any]],
    *,
    min_single_breaks: int = 5,
    include_pdf: bool = False,
) -> tuple[int, Counter[str]]:
    field_counts: Counter[str] = Counter()
    records_changed = 0
    for record in records:
        changed = normalize_item(record, min_single_breaks=min_single_breaks, include_pdf=include_pdf)
        if changed:
            records_changed += 1
            field_counts.update(changed)
    return records_changed, field_counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize paragraph blank lines in existing item Markdown fields.")
    parser.add_argument("--items", type=Path, default=DEFAULT_ITEMS)
    parser.add_argument("--write", action="store_true", help="Write the normalized records back to the JSONL file.")
    parser.add_argument("--include-pdf", action="store_true", help="Also normalize pdf-* article_markdown methods.")
    parser.add_argument("--min-single-breaks", type=int, default=5)
    args = parser.parse_args()

    records = load_jsonl(args.items)
    records_changed, field_counts = normalize_records(
        records,
        min_single_breaks=args.min_single_breaks,
        include_pdf=args.include_pdf,
    )
    if args.write and records_changed:
        write_jsonl(args.items, records)

    mode = "wrote" if args.write else "dry-run"
    print(f"{mode}: records_changed={records_changed}")
    for key, count in sorted(field_counts.items()):
        print(f"{key}={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
