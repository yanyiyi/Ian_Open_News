#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference"
DATABASE = ROOT / "database"
INOREADER_DIR = REFERENCE / "Inoreader export 20260618"
SUBSCRIPTIONS = INOREADER_DIR / "subscriptions.xml"
STARRED = INOREADER_DIR / "starred.json"
XLSX = REFERENCE / "[開放科技] 研究、議題與新聞跟追表.xlsx"

TRACK_DH = "digital-humanities-local-knowledge"
TRACK_OPEN = "open-tech-open-industry"
TRACK_UNKNOWN = "unclassified"

DH_KEYWORDS = [
    "記憶庫",
    "文化局",
    "文化資源",
    "文資",
    "文史",
    "地方",
    "博物",
    "典藏",
    "眷村",
    "民眾書寫",
    "聚珍",
    "中醫藥文化記憶",
    "牛犁",
]

OPEN_KEYWORDS = [
    "OpenTech",
    "Open Source",
    "open source",
    "開放資料",
    "開放原始碼",
    "開放科技",
    "開源",
    "COSCUP",
    "SITCON",
    "OCF",
    "開放文化基金會",
    "數位人權",
    "資料治理",
    "數據治理",
    "Creative Commons",
    "FSF",
    "Mozilla",
    "GovInsider",
    "FOSDEM",
    "Open Knowledge",
    "資料標準",
]


def stable_id(prefix: str, *parts: object) -> str:
    raw = "||".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def clean_text(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def first_url(values: list[str]) -> str:
    joined = "\n".join(values)
    match = re.search(r"https?://[^\s)）\"'>]+", joined)
    if match:
        return match.group(0)
    return ""


def as_date_from_epoch(value: object) -> str:
    if value in (None, "", 0, "0"):
        return ""
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def infer_track(*values: object) -> str:
    haystack = " ".join(clean_text(value) for value in values if value)
    if any(keyword in haystack for keyword in OPEN_KEYWORDS):
        return TRACK_OPEN
    if any(keyword in haystack for keyword in DH_KEYWORDS):
        return TRACK_DH
    return TRACK_UNKNOWN


def infer_source_type(name: str, feed_url: str, site_url: str) -> str:
    text = f"{name} {feed_url} {site_url}"
    lower = text.lower()
    if "keyword-monitoring-" in lower:
        return "inoreader-monitor"
    if "facebook.com" in lower or "(facebook)" in lower:
        return "facebook"
    if "google.com/alerts" in lower or "google 快訊" in text or "google alert" in lower:
        return "google-alert"
    if "youtube.com" in lower:
        return "youtube"
    if any(token in lower for token in ["podcast", "soundon.fm", "anchor.fm", "captivate.fm"]):
        return "podcast"
    return "rss"


def source_record(
    *,
    name: str,
    source_group: str,
    feed_url: str = "",
    site_url: str = "",
    track: str | None = None,
    source_type: str | None = None,
    status: str = "active",
    notes: str = "",
) -> dict:
    name = clean_text(name) or clean_text(site_url) or clean_text(feed_url) or "未命名來源"
    source_group = clean_text(source_group) or "未分組"
    track = track or infer_track(source_group, name, feed_url, site_url)
    source_type = source_type or infer_source_type(name, feed_url, site_url)
    return {
        "id": stable_id("src", source_group, name, feed_url, site_url),
        "track": track,
        "name": name,
        "source_group": source_group,
        "source_type": source_type,
        "feed_url": feed_url,
        "site_url": site_url,
        "status": status,
        "notes": notes,
    }


def default_review() -> dict:
    return {
        "angle": "",
        "research_status": "not-started",
        "structure_review": "pending",
        "line_review": "pending",
        "target_reader_review": "pending",
        "fact_check": "pending",
        "notes": "",
    }


def parse_opml(path: Path) -> tuple[list[dict], dict[str, dict]]:
    if not path.exists():
        return [], {}
    root = ET.parse(path).getroot()
    body = root.find("body")
    records: list[dict] = []
    by_feed: dict[str, dict] = {}

    def walk(node: ET.Element, stack: list[str]) -> None:
        title = node.attrib.get("title") or node.attrib.get("text") or ""
        if node.attrib.get("type") == "rss":
            source_group = " / ".join(part for part in stack if part) or "ROOT"
            feed_url = node.attrib.get("xmlUrl", "")
            site_url = node.attrib.get("htmlUrl", "")
            record = source_record(
                name=title,
                source_group=source_group,
                feed_url=feed_url,
                site_url=site_url,
            )
            records.append(record)
            if feed_url:
                by_feed[feed_url] = record
            if site_url:
                by_feed[site_url] = record
        for child in node.findall("outline"):
            walk(child, stack + ([title] if title else []))

    if body is not None:
        for child in body.findall("outline"):
            walk(child, [])
    return records, by_feed


def parse_starred(path: Path, source_by_feed: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    items: list[dict] = []
    extra_sources: list[dict] = []
    seen_sources: set[str] = set(source["id"] for source in source_by_feed.values())

    for entry in data.get("items", []):
        origin = entry.get("origin") or {}
        stream_id = origin.get("streamId", "")
        feed_url = stream_id.removeprefix("feed/")
        source = source_by_feed.get(feed_url) or source_by_feed.get(origin.get("htmlUrl", ""))
        if not source:
            source = source_record(
                name=origin.get("title") or entry.get("author") or "Inoreader starred",
                source_group="Inoreader starred",
                feed_url=feed_url,
                site_url=origin.get("htmlUrl", ""),
            )
            if source["id"] not in seen_sources:
                extra_sources.append(source)
                seen_sources.add(source["id"])
        categories = [
            cat.split("/label/", 1)[1]
            for cat in entry.get("categories", [])
            if "/label/" in cat
        ]
        title = clean_text(entry.get("title"), 300) or "(無標題)"
        canonical = (entry.get("canonical") or [{}])[0].get("href", "")
        alternate = (entry.get("alternate") or [{}])[0].get("href", "")
        url = canonical or alternate or origin.get("htmlUrl", "")
        summary = clean_text((entry.get("summary") or {}).get("content", ""), 1200)
        track = infer_track(source.get("track"), source.get("source_group"), source.get("name"), " ".join(categories), title, summary)
        if track == TRACK_UNKNOWN:
            track = source.get("track", TRACK_UNKNOWN)
        items.append(
            {
                "id": stable_id("item", url, entry.get("id"), title),
                "track": track,
                "status": "inbox",
                "priority": "normal",
                "title": title,
                "url": url,
                "source_id": source["id"],
                "source_name": source["name"],
                "author": clean_text(entry.get("author"), 160),
                "published_at": as_date_from_epoch(entry.get("published")),
                "captured_at": as_date_from_epoch(entry.get("starred") or entry.get("crawlTimeMsec", "")[:-3]),
                "summary": summary,
                "tags": categories,
                "origin": "inoreader-starred",
                "reference": {
                    "file": str(path.relative_to(ROOT)),
                    "record_id": entry.get("id", ""),
                    "stream_id": stream_id,
                },
                "review": default_review(),
            }
        )
    return items, extra_sources


def read_xlsx_rows(path: Path) -> dict[str, list[list[str]]]:
    if not path.exists():
        return {}
    ns = {
        "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with zipfile.ZipFile(path) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("a:si", ns):
                shared_strings.append("".join(t.text or "" for t in si.findall(".//a:t", ns)))
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}

        def column_index(cell_ref: str) -> int:
            letters = re.match(r"[A-Z]+", cell_ref).group(0)
            number = 0
            for letter in letters:
                number = number * 26 + ord(letter) - 64
            return number - 1

        def cell_value(cell: ET.Element) -> str:
            value = cell.find("a:v", ns)
            if value is None:
                return ""
            text = value.text or ""
            if cell.attrib.get("t") == "s" and text.isdigit():
                index = int(text)
                if index < len(shared_strings):
                    return shared_strings[index]
            return text

        sheets: dict[str, list[list[str]]] = {}
        for sheet in workbook.findall("a:sheets/a:sheet", ns):
            name = sheet.attrib.get("name", "")
            rel_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = relmap[rel_id]
            sheet_path = "xl/" + target.lstrip("/") if not target.startswith("xl/") else target
            root = ET.fromstring(zf.read(sheet_path))
            rows: list[list[str]] = []
            for row in root.findall(".//a:sheetData/a:row", ns):
                values: list[str] = []
                for cell in row.findall("a:c", ns):
                    index = column_index(cell.attrib["r"])
                    while len(values) < index:
                        values.append("")
                    values.append(clean_text(cell_value(cell)))
                rows.append(values)
            sheets[name] = rows
        return sheets


def parse_xlsx(path: Path) -> tuple[list[dict], list[dict]]:
    sheets = read_xlsx_rows(path)
    items: list[dict] = []
    sources: list[dict] = []
    for sheet_name, rows in sheets.items():
        if not rows:
            continue
        source = source_record(
            name=f"Excel: {sheet_name}",
            source_group="既有 Excel 跟追表",
            track=TRACK_OPEN,
            source_type="spreadsheet",
            status="archived",
            notes="由 reference/[開放科技] 研究、議題與新聞跟追表.xlsx 匯入。",
        )
        sources.append(source)
        header = [clean_text(cell) for cell in rows[0]]
        for row_index, row in enumerate(rows[1:], start=2):
            padded = row + [""] * max(0, len(header) - len(row))
            raw = {
                header[index] or f"column_{index + 1}": clean_text(padded[index])
                for index in range(min(len(header), len(padded)))
                if clean_text(padded[index])
            }
            if len(raw) < 2:
                continue
            title = (
                raw.get("名稱")
                or raw.get("名詞")
                or raw.get("單位")
                or raw.get("分類")
                or raw.get("類別")
                or ""
            )
            if not title:
                continue
            url = (
                raw.get("原始網址")
                or raw.get("最新網址")
                or raw.get("追蹤網站")
                or raw.get("可追蹤頁面")
                or first_url(list(raw.values()))
            )
            summary = raw.get("摘要") or raw.get("定義") or raw.get("備註") or raw.get("會議公告議程") or ""
            tags = [sheet_name]
            for key in ["分類", "類別", "相關觀念", "提出單位", "來源"]:
                if raw.get(key):
                    tags.append(raw[key])
            items.append(
                {
                    "id": stable_id("item", "xlsx", sheet_name, row_index, title, url),
                    "track": TRACK_OPEN,
                    "status": "archived",
                    "priority": "normal",
                    "title": clean_text(title, 300),
                    "url": url,
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "author": clean_text(raw.get("作者") or raw.get("收錄者") or raw.get("出席者"), 160),
                    "published_at": raw.get("新聞日期") or raw.get("更新日期") or raw.get("前次更新日期") or raw.get("時間") or "",
                    "captured_at": raw.get("最後檢視日期") or raw.get("收錄日期") or "",
                    "summary": clean_text(summary, 1200),
                    "tags": [tag for tag in tags if tag],
                    "origin": f"xlsx:{sheet_name}",
                    "reference": {
                        "file": str(path.relative_to(ROOT)),
                        "sheet": sheet_name,
                        "row": row_index,
                        "raw_columns": raw,
                    },
                    "review": default_review(),
                }
            )
    return items, sources


def unique_by_id(records: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for record in records:
        deduped[record["id"]] = record
    return [deduped[key] for key in sorted(deduped)]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import existing Inoreader and Excel references into database/*.jsonl")
    parser.add_argument("--database", type=Path, default=DATABASE)
    args = parser.parse_args()

    sources, source_by_feed = parse_opml(SUBSCRIPTIONS)
    starred_items, extra_sources = parse_starred(STARRED, source_by_feed)
    xlsx_items, xlsx_sources = parse_xlsx(XLSX)

    all_sources = unique_by_id(sources + extra_sources + xlsx_sources)
    all_items = unique_by_id(starred_items + xlsx_items)

    write_jsonl(args.database / "sources.jsonl", all_sources)
    write_jsonl(args.database / "items.jsonl", all_items)

    print(f"wrote {len(all_sources)} sources to {args.database / 'sources.jsonl'}")
    print(f"wrote {len(all_items)} items to {args.database / 'items.jsonl'}")


if __name__ == "__main__":
    main()
