#!/usr/bin/env python3
"""Extract selected PDF table regions as layout-preserving Markdown sidecars.

Automatic PDF table detection is unreliable for tables without vertical rules.
This tool accepts reviewed page/bounding-box regions, optionally maps positioned
words into reviewed TSV columns, and joins continued tables into one supplement.
"""
from __future__ import annotations

import argparse
import bisect
import re
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PDF_TABLES_DIR = ROOT / "database" / "pdf-tables"


def parse_region(value: str) -> tuple[str, int, tuple[float, float, float, float]]:
    parts = value.split(":")
    if len(parts) != 6:
        raise argparse.ArgumentTypeError("region 必須是 TABLE:PAGE:X0:TOP:X1:BOTTOM")
    table, page, x0, top, x1, bottom = parts
    try:
        return table, int(page), (float(x0), float(top), float(x1), float(bottom))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"region 數字格式錯誤：{value}") from exc


def parse_columns(value: str) -> tuple[tuple[str, int], list[float]]:
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("columns 必須是 TABLE:PAGE:X0,X1,...,XEND")
    table, page_text, edges_text = parts
    try:
        page = int(page_text)
        edges = [float(part) for part in edges_text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"columns 數字格式錯誤：{value}") from exc
    if len(edges) < 3 or edges != sorted(edges) or len(set(edges)) != len(edges):
        raise argparse.ArgumentTypeError("columns 至少要有 3 個由小到大且不重複的邊界")
    return (table, page), edges


def clean_table_text(value: str, page_number: int) -> str:
    lines = [line.rstrip() for line in str(value or "").replace("\r", "").splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == str(page_number):
        lines.pop()
    nonempty = [line for line in lines if line.strip()]
    indent = min((len(line) - len(line.lstrip()) for line in nonempty), default=0)
    lines = [line[indent:] if line.strip() else "" for line in lines]
    return "\n".join(lines).strip()


def extract_tsv_rows(page: object, bbox: tuple[float, float, float, float], edges: list[float]) -> str:
    """Map positioned PDF words into reviewed columns and visual rows."""
    words = page.crop(bbox).extract_words(x_tolerance=1, y_tolerance=3) or []
    rows: list[tuple[float, list[dict]]] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        top = float(word["top"])
        row = next((candidate for candidate in rows if abs(candidate[0] - top) < 2), None)
        if row is None:
            row = (top, [])
            rows.append(row)
        row[1].append(word)
    output: list[str] = []
    for _top, row_words in rows:
        cells: list[list[str]] = [[] for _ in range(len(edges) - 1)]
        for word in sorted(row_words, key=lambda item: float(item["x0"])):
            index = bisect.bisect_right(edges, float(word["x0"])) - 1
            index = min(max(index, 0), len(cells) - 1)
            cells[index].append(str(word["text"]))
        output.append("\t".join(" ".join(cell).strip() for cell in cells).rstrip())
    return "\n".join(line for line in output if line.strip()).strip()


def extract_tables(
    pdf_path: Path,
    regions: list[tuple[str, int, tuple[float, float, float, float]]],
    columns: dict[tuple[str, int], list[float]] | None = None,
) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise SystemExit("需要 pdfplumber；請使用 Codex bundled Python 執行。") from exc

    columns = columns or {}
    grouped: OrderedDict[str, list[tuple[int, str, str]]] = OrderedDict()
    with pdfplumber.open(pdf_path) as pdf:
        for table, page_number, bbox in regions:
            if page_number < 1 or page_number > len(pdf.pages):
                raise SystemExit(f"頁碼超出 PDF 範圍：{page_number}")
            page = pdf.pages[page_number - 1]
            edges = columns.get((table, page_number))
            if edges:
                cleaned = extract_tsv_rows(page, bbox, edges)
                fence_language = "tsv"
            else:
                text = page.crop(bbox).extract_text(layout=True, x_tolerance=2, y_tolerance=3) or ""
                cleaned = clean_table_text(text, page_number)
                fence_language = "text"
            if not cleaned:
                raise SystemExit(f"Table {table} 第 {page_number} 頁沒有抽到文字。")
            grouped.setdefault(table, []).append((page_number, cleaned, fence_language))

    sections = [
        "# PDF 表格版面修復",
        "",
        "以下表格依原 PDF 的頁面座標抽取，保留欄位位置；跨頁續表已合併。",
    ]
    for table, parts in grouped.items():
        pages = ", ".join(str(page) for page, _text, _language in parts)
        languages = {language for _page, _text, language in parts}
        if len(languages) == 1:
            fence_language = parts[0][2]
            sections.extend(["", f"## Table {table}（PDF 第 {pages} 頁）", "", f"```{fence_language}"])
            for index, (_page, table_text, _language) in enumerate(parts):
                if index:
                    sections.append("[continued]")
                sections.append(table_text)
            sections.append("```")
        else:
            sections.extend(["", f"## Table {table}（PDF 第 {pages} 頁）"])
            for index, (_page, table_text, fence_language) in enumerate(parts):
                if index:
                    sections.extend(["", "[continued]", ""])
                else:
                    sections.append("")
                sections.extend([f"```{fence_language}", table_text, "```"])
    return "\n".join(sections).strip() + "\n"


def safe_item_id(value: str) -> str:
    item_id = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not item_id:
        raise SystemExit("item id 不可為空。")
    return item_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract reviewed PDF table regions into a Markdown sidecar.")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--item-id", help="Ian Open News item id; writes database/pdf-tables/<id>.md")
    parser.add_argument("--output", type=Path, help="Explicit output Markdown path for general use")
    parser.add_argument("--region", action="append", type=parse_region, required=True)
    parser.add_argument(
        "--columns",
        action="append",
        type=parse_columns,
        default=[],
        help="Optional reviewed column edges: TABLE:PAGE:X0,X1,...,XEND; emits TSV",
    )
    args = parser.parse_args()

    markdown = extract_tables(args.pdf, args.region, dict(args.columns))
    if args.output:
        output = args.output.expanduser()
    elif args.item_id:
        output = PDF_TABLES_DIR / f"{safe_item_id(args.item_id)}.md"
    else:
        parser.error("請提供 --output 或 --item-id。")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    try:
        display = output.relative_to(ROOT)
    except ValueError:
        display = output
    print(f"wrote {display} chars={len(markdown)} tables={len({r[0] for r in args.region})}")


if __name__ == "__main__":
    main()
