#!/usr/bin/env python3
"""Build reading-order Markdown from reviewed PDF regions and repaired tables."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_table_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"(?m)^## Table ([^（\s]+).*?$", markdown))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group(1)] = markdown[match.start():end].strip()
    return sections


def clean_region_text(value: str) -> str:
    lines = [line.strip() for line in str(value or "").replace("\r", "").splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if not line:
            continue
        compact = re.sub(r"\s+", " ", line).strip()
        if re.fullmatch(r"\d{1,2}", compact):
            continue
        if re.fullmatch(r"N\.?\s*Robinson", compact, flags=re.I):
            continue
        if "Government Information Quarterly 43 (2026) 102133" in compact:
            continue
        cleaned.append(compact)
    text = "\n".join(cleaned)
    text = re.sub(r"(?<=\w)-\n(?=[a-z])", "", text)
    return text.strip()


def build_article(pdf_path: Path, tables_path: Path, plan_path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit("需要 pdfplumber；請使用 Codex bundled Python 執行。") from exc

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    segments = plan.get("segments") if isinstance(plan, dict) else None
    if not isinstance(segments, list) or not segments:
        raise SystemExit("layout plan 必須包含非空的 segments 陣列。")
    tables = load_table_sections(tables_path.read_text(encoding="utf-8"))
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for index, segment in enumerate(segments, start=1):
            if not isinstance(segment, dict):
                raise SystemExit(f"segment {index} 格式錯誤。")
            kind = str(segment.get("type") or "")
            if kind == "table":
                table_id = str(segment.get("id") or "")
                table = tables.get(table_id)
                if not table:
                    raise SystemExit(f"segment {index} 找不到 Table {table_id}。")
                parts.append(table)
                continue
            if kind != "text":
                raise SystemExit(f"segment {index} type 必須是 text 或 table。")
            page_number = int(segment.get("page") or 0)
            bbox = segment.get("bbox")
            if page_number < 1 or page_number > len(pdf.pages):
                raise SystemExit(f"segment {index} 頁碼超出範圍：{page_number}")
            if not isinstance(bbox, list) or len(bbox) != 4:
                raise SystemExit(f"segment {index} bbox 必須有 4 個數字。")
            box = tuple(float(value) for value in bbox)
            text = pdf.pages[page_number - 1].crop(box).extract_text(x_tolerance=2, y_tolerance=3) or ""
            cleaned = clean_region_text(text)
            if cleaned:
                parts.append(cleaned)
    title = str(plan.get("title") or "PDF 版面整合全文").strip()
    return f"# {title}\n\n" + "\n\n".join(parts).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Integrate reviewed PDF text regions and repaired tables in reading order.")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--tables", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    markdown = build_article(args.pdf, args.tables, args.plan)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(
        f"wrote {args.output} chars={len(markdown)} "
        f"tables={markdown.count('```tsv')} continued={markdown.count('[continued]')}"
    )


if __name__ == "__main__":
    main()
