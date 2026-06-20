#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import html
import json
import mimetypes
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, unquote, urljoin, urlparse
import hashlib
from zoneinfo import ZoneInfo

from page_metadata import (
    attrs_from_tag,
    complete_item_metadata,
    enrich_item_metadata,
    fetch_page_metadata,
    infer_language_from_text,
    text_to_markdown,
    unwrap_google_alert_url,
)


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
SOURCES = DATABASE / "sources.jsonl"
ITEMS = DATABASE / "items.jsonl"
REJECTED_ITEMS = DATABASE / "rejected-items.jsonl"
REVIEW_EVENTS = DATABASE / "review-events.jsonl"
TRIAGE_KEYWORDS = DATABASE / "triage-keywords.json"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"
RSS_FETCH_STATUS = ROOT / ".cache" / "rss-fetch-status.json"
DATA_COMMIT_STATUS = ROOT / ".cache" / "data-autocommit-status.json"
DATA_AUTOCOMMIT_INTERVAL_SECONDS = 30 * 60

TRACKS = [
    ("digital-humanities-local-knowledge", "數位人文與在地知識建構"),
    ("open-tech-open-industry", "開放科技與開放產業發展"),
    ("unclassified", "未分類"),
]
TRACK_META = {
    "digital-humanities-local-knowledge": {
        "label": "數位人文與在地知識建構",
        "short": "人文與在地知識",
        "class": "humanities",
        "description": "地方知識、文化記憶、數位典藏、博物館、檔案與社群共筆。",
        "entry": "進入人文工作台",
    },
    "open-tech-open-industry": {
        "label": "開放科技與開放產業發展",
        "short": "開放科技",
        "class": "opentech",
        "description": "開源、開放資料、資料治理、標準、授權、公共數位基礎建設與開放產業。",
        "entry": "進入開放科技工作台",
    },
    "unclassified": {
        "label": "未分類",
        "short": "未分類",
        "class": "neutral",
        "description": "還沒決定要放進哪一條主線的來源與項目。",
        "entry": "查看未分類",
    },
}
TRACK_ORDER = ["open-tech-open-industry", "digital-humanities-local-knowledge", "unclassified"]
LOCAL_TIMEZONE = ZoneInfo("Asia/Taipei")
SOURCE_TYPES = ["rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor", "spreadsheet", "manual"]
SOURCE_STATUSES = ["active", "paused", "archived"]
FETCH_FREQUENCIES = ["daily", "weekly", "monthly", "paused"]
SOURCE_TYPE_LABELS = {
    "rss": "RSS / 網站",
    "google-alert": "Google 快訊",
    "youtube": "YouTube",
    "podcast": "Podcast",
    "facebook": "Facebook",
    "inoreader-monitor": "Inoreader 關鍵字",
    "spreadsheet": "既有表格",
    "manual": "手動加入",
}
SOURCE_TYPE_HELP = {
    "rss": "一般網站或部落格 feed，可由本機或 GitHub Actions 自動抓。",
    "google-alert": "Google Alert 匯出的 feed，適合追關鍵字。",
    "youtube": "YouTube 頻道 feed，適合追影片發布。",
    "podcast": "Podcast feed，適合追音訊節目。",
    "facebook": "從 Inoreader 或舊流程留下的 Facebook 來源，通常不直接由 GitHub 抓。",
    "inoreader-monitor": "Inoreader 關鍵字監測來源，保留作為舊流程對照。",
    "spreadsheet": "從既有 Excel 跟追表匯入的來源。",
    "manual": "在本機網頁手動加入的來源。",
}
SOURCE_STATUS_LABELS = {
    "active": "啟用",
    "paused": "暫停",
    "archived": "封存",
}
FETCH_FREQUENCY_LABELS = {
    "daily": "每天抓",
    "weekly": "每週抓",
    "monthly": "每月抓",
    "paused": "暫停抓取",
}
COMMAND_ICONS = {
    "fetch_rss": "rss",
    "validate": "check-circle",
    "apply_triage_keywords": "filter",
    "analyze_source_health": "pulse",
    "export_sqlite": "database",
    "render_ghpages_reader": "publish",
    "enrich_reader_metadata": "image",
    "enrich_article_summaries": "text-lines",
    "codex_enrich_reviews": "sparkle",
    "git_status": "branch",
    "git_diff_stat": "chart",
    "commit_database_state": "save",
}
COMMAND_SHORTCUTS = {
    "fetch_rss": "R",
    "validate": "V",
    "apply_triage_keywords": "F",
    "analyze_source_health": "H",
    "export_sqlite": "D",
    "render_ghpages_reader": "P",
    "enrich_reader_metadata": "T",
    "enrich_article_summaries": "S",
    "codex_enrich_reviews": "C",
    "git_status": "G",
    "git_diff_stat": "I",
    "commit_database_state": "K",
}
DATA_AUTOCOMMIT_FILES = [ITEMS, REVIEW_EVENTS, SOURCES]
DATA_AUTOCOMMIT_LOCK = threading.Lock()
REJECTION_REASON_CATEGORIES = [
    "活動公告/宣傳",
    "純紀錄型資料",
    "資料太舊",
    "主線關聯弱",
    "社群內部消息",
    "重複/已涵蓋",
    "地緣脈絡非台資訊",
]
DEFAULT_REJECTION_REASONS = list(REJECTION_REASON_CATEGORIES)
SOURCE_KEYWORD_EXCLUSION_REASON = "單一 RSS 專屬關鍵字排除"
REJECTION_REASON_ALIASES = {
    "內容偏活動公告或宣傳，暫不整理。": "活動公告/宣傳",
    "活動公告": "活動公告/宣傳",
    "宣傳": "活動公告/宣傳",
    "記憶庫純紀錄型資料": "純紀錄型資料",
    "只是短訊或碎片，不足以形成文章。": "純紀錄型資料",
    "其他類型文章": "純紀錄型資料",
    "資料太舊": "資料太舊",
    "資訊過舊或缺少可查證來源。": "資料太舊",
    "已經是建議不要看": "主線關聯弱",
    "和兩條主線關聯太弱。": "主線關聯弱",
    "和 OCF 關心的開放科技議題發展關係不大": "主線關聯弱",
    "和 ocf 關心的開放科技議題發展關係不大": "主線關聯弱",
    SOURCE_KEYWORD_EXCLUSION_REASON: "主線關聯弱",
    "社群內部消息，無關": "社群內部消息",
    "社群內部消息": "社群內部消息",
    "來源重複，已由其他資料涵蓋。": "重複/已涵蓋",
    "重複": "重複/已涵蓋",
    "已涵蓋": "重複/已涵蓋",
    "中國訊息": "地緣脈絡非台資訊",
    "中國資料": "地緣脈絡非台資訊",
    "地緣脈絡非台資訊": "地緣脈絡非台資訊",
}

COMMANDS = {
    "fetch_rss": {
        "label": "立刻抓 RSS 候選",
        "description": "先抓到 RSS 待整理，不直接寫進正式資料庫；抓完會接著用 Codex 補閱讀建議、三個理由與中文摘要。",
        "button": "抓到 RSS 待整理",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "local_rss_daily.py"),
        ],
    },
    "validate": {
        "label": "驗證資料庫",
        "description": "檢查 JSONL 欄位、主線分類、來源關聯是否正確。送 PR 前先按這個。",
        "button": "檢查資料有沒有壞",
        "command": [sys.executable, str(ROOT / "scripts" / "validate_database.py")],
    },
    "apply_triage_keywords": {
        "label": "重新跑本機規則/關鍵字初篩",
        "description": "把目前 RSS 待整理重新套用關鍵字、過去不收紀錄與過去收錄類型。這是本機規則判斷，不是 Codex 生成摘要。",
        "button": "更新初篩建議",
        "command": [sys.executable, str(ROOT / "scripts" / "apply_triage_keywords.py")],
    },
    "analyze_source_health": {
        "label": "更新 RSS 來源健康評估",
        "description": "彙整近期收下、不收、候選與 RSS 抓取結果，替每個來源建議抓取頻率、是否暫停或重設個別關鍵字。適合兩週跑一次。",
        "button": "更新來源健康評估",
        "command": [sys.executable, str(ROOT / "scripts" / "analyze_source_health.py")],
    },
    "export_sqlite": {
        "label": "匯出 SQLite",
        "description": "把 JSONL 正本轉成 .cache/knowledge.sqlite，方便用資料庫工具查詢。",
        "button": "做一份查詢用資料庫",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "export_sqlite.py"),
            "--output",
            str(ROOT / ".cache" / "knowledge.sqlite"),
        ],
    },
    "render_ghpages_reader": {
        "label": "產生 GitHub Pages 閱讀版",
        "description": "輸出 docs/reader/index.html，只顯示開放科技主線的精選文章、小消息與觀點文章，可交給 GitHub Pages 發布。",
        "button": "更新線上閱讀版",
        "command": [sys.executable, str(ROOT / "scripts" / "render_ghpages_reader.py")],
    },
    "enrich_reader_metadata": {
        "label": "補閱讀卡圖片、描述與主文",
        "description": "連到閱讀區文章的原始網址，抓封面圖、標題、描述與可抽取的原始主文，讓卡片比較像線上報，也讓單篇頁能閱讀全文。",
        "button": "補閱讀區資料",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "enrich_reading_metadata.py"),
            "--reader-only",
            "--only-missing-image",
            "--limit",
            "40",
        ],
    },
    "enrich_article_summaries": {
        "label": "用本機規則重抓待整理摘要",
        "description": "連到待整理中建議收的原始網址，抓正文後用本機規則重寫摘要與 3 點閱讀理由。這不是 Codex 生成；真正 Codex 生成會在單篇中標為「來源：Codex」。",
        "button": "用規則重寫摘要",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "enrich_article_summaries.py"),
            "--status",
            "inbox",
            "--recommendation",
            "suggest-keep",
            "--workers",
            "8",
            "--timeout",
            "8",
        ],
    },
    "codex_enrich_reviews": {
        "label": "用 Codex 補閱讀建議與摘要",
        "description": "針對 RSS 待整理與閱讀區中還沒有 Codex review 的項目，產生給 Ian 的一句話推薦、三個閱讀理由、中文標題與中文摘要。",
        "button": "補 Codex 建議",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--target",
            "both",
            "--workflow-scope",
            "--limit",
            "18",
            "--batch-size",
            "6",
        ],
    },
    "commit_database_state": {
        "label": "送 commit 儲存資料庫狀態",
        "description": "只把 database/items.jsonl、database/review-events.jsonl、database/sources.jsonl 目前變更送成一個自訂紀錄 commit；背景每 30 分鐘也會自動檢查一次。",
        "button": "送 commit 儲存狀態",
        "internal": "commit_database_state",
    },
    "git_status": {
        "label": "查看檔案變更",
        "description": "列出目前哪些檔案被新增或修改，方便確認接下來要不要開 PR。",
        "button": "看有哪些檔案變了",
        "command": ["git", "status", "--short"],
    },
    "git_diff_stat": {
        "label": "查看變更摘要",
        "description": "只看每個檔案改了多少行，不展開完整內容。",
        "button": "看每個檔案改多少",
        "command": ["git", "diff", "--stat"],
    },
}


def stable_id(prefix: str, *parts: object) -> str:
    raw = "||".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def clean_text(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
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


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold() if "}" in tag else tag.casefold()


def fetchable_http_url(value: object) -> str:
    url = clean_text(value)
    return url if url.startswith(("http://", "https://")) else ""


def host_label(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.removeprefix("www.")
    return host or url


def source_add_href(feed_url: str, track: str, name: str = "", site_url: str = "") -> str:
    params = {
        "track": track if track in TRACK_META else "digital-humanities-local-knowledge",
        "source_type": "rss",
        "source_group": "Manual RSS",
        "feed_url": feed_url,
        "site_url": site_url,
        "name": name or host_label(feed_url),
    }
    return "/sources/new?" + urlencode(params)


def read_preview_document(url: str, timeout: int = 8, max_bytes: int = 900_000) -> tuple[str, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "IanOpenNewsBot/1.0 preview (+local web form)",
            "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,application/atom+xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_bytes)
    return final_url, content_type, raw


def decode_preview_text(raw: bytes, content_type: str) -> str:
    charset_match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    charset = charset_match.group(1) if charset_match else "utf-8"
    return raw.decode(charset, errors="replace")


def feed_metadata_from_xml(raw: bytes, final_url: str) -> dict:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return {}
    root_name = local_name(root.tag)
    if root_name == "rss":
        channel = next((child for child in list(root) if local_name(child.tag) == "channel"), None)
        if channel is None:
            return {}
        title = clean_text(next((child.text for child in list(channel) if local_name(child.tag) == "title"), ""), 220)
        site_url = clean_text(next((child.text for child in list(channel) if local_name(child.tag) == "link"), ""))
        description = clean_text(next((child.text for child in list(channel) if local_name(child.tag) == "description"), ""), 500)
        entry_count = sum(1 for child in list(channel) if local_name(child.tag) == "item")
        return {
            "is_feed": True,
            "feed_type": "RSS",
            "feed_title": title,
            "site_url": site_url,
            "description": description,
            "entry_count": entry_count,
            "final_url": final_url,
        }
    if root_name == "feed":
        title = clean_text(next((child.text for child in list(root) if local_name(child.tag) == "title"), ""), 220)
        site_url = ""
        for child in list(root):
            if local_name(child.tag) != "link":
                continue
            attrs = {str(key).casefold(): str(value) for key, value in child.attrib.items()}
            rel = attrs.get("rel", "alternate").casefold()
            if rel == "alternate" and attrs.get("href"):
                site_url = urljoin(final_url, attrs["href"])
                break
        entry_count = sum(1 for child in list(root) if local_name(child.tag) == "entry")
        return {
            "is_feed": True,
            "feed_type": "Atom",
            "feed_title": title,
            "site_url": site_url,
            "description": "",
            "entry_count": entry_count,
            "final_url": final_url,
        }
    return {}


def discover_feed_links(html_text: str, final_url: str) -> list[dict]:
    feeds: list[dict] = []
    seen: set[str] = set()

    def add_feed(href: str, title: str, source: str, feed_type: str = "") -> None:
        feed_url = urljoin(final_url, html.unescape(href).strip())
        if not feed_url.startswith(("http://", "https://")):
            return
        key = feed_url.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        feeds.append(
            {
                "url": feed_url,
                "title": clean_text(title, 160) or "RSS / Atom feed",
                "type": clean_text(feed_type, 60) or "RSS / Atom",
                "source": source,
            }
        )

    for match in re.finditer(r"<link\b[^>]*>", html_text, flags=re.I | re.S):
        attrs = attrs_from_tag(match.group(0))
        rel = attrs.get("rel", "").casefold()
        feed_type = attrs.get("type", "")
        feed_type_lower = feed_type.casefold()
        title = attrs.get("title") or attrs.get("href") or "RSS / Atom feed"
        if "alternate" not in rel.split() or not attrs.get("href"):
            continue
        if any(token in feed_type_lower for token in ["rss", "atom", "xml"]) or re.search(r"\b(rss|atom|feed)\b", title, flags=re.I):
            add_feed(attrs["href"], title, "page-link", feed_type)

    for match in re.finditer(r"(?is)<a\b([^>]*)>(.*?)</a>", html_text):
        attrs = attrs_from_tag(match.group(1))
        href = attrs.get("href", "")
        label = clean_text(match.group(2), 160)
        if not href or not re.search(r"\b(rss|atom|feed)\b|訂閱|摘要", f"{href} {label}", flags=re.I):
            continue
        add_feed(href, label or href, "page-anchor")
        if len(feeds) >= 8:
            break
    return feeds[:8]


def build_url_preview(url: str, track: str) -> dict:
    original_url = clean_text(url)
    url = fetchable_http_url(unwrap_google_alert_url(original_url))
    if not url:
        return {"ok": False, "error": "請填入 http 或 https 開頭的網址。"}

    sources = load_jsonl(SOURCES)
    existing_feeds = {clean_text(source.get("feed_url")).rstrip("/") for source in sources if source.get("feed_url")}
    metadata: dict = {}
    metadata_error = ""
    try:
        metadata = fetch_page_metadata(url, timeout=8)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        metadata_error = str(exc)

    final_url = clean_text(metadata.get("final_url") or url)
    content_type = ""
    raw = b""
    document_error = ""
    try:
        final_url, content_type, raw = read_preview_document(url, timeout=8)
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        document_error = str(exc)

    feed_info = feed_metadata_from_xml(raw, final_url) if raw else {}
    html_text = decode_preview_text(raw, content_type) if raw else ""
    feed_suggestions = [] if feed_info else discover_feed_links(html_text, final_url)
    if feed_info:
        title = feed_info.get("feed_title") or metadata.get("title") or host_label(final_url)
        feed_suggestions = [
            {
                "url": final_url,
                "title": title,
                "type": feed_info.get("feed_type") or "RSS / Atom",
                "source": "current-url",
            }
        ]

    enriched_feeds = []
    for feed in feed_suggestions:
        feed_url = clean_text(feed.get("url"))
        key = feed_url.rstrip("/")
        feed_title = clean_text(feed.get("title"), 160) or clean_text(metadata.get("title"), 160) or host_label(feed_url)
        site_url = clean_text(feed_info.get("site_url") if feed_info else final_url)
        enriched_feeds.append(
            {
                **feed,
                "url": feed_url,
                "title": feed_title,
                "exists": key in existing_feeds,
                "add_url": source_add_href(feed_url, track, feed_title, site_url),
            }
        )

    title = clean_text(metadata.get("title") or feed_info.get("feed_title"), 300)
    description = clean_text(metadata.get("description") or feed_info.get("description") or metadata.get("excerpt"), 900)
    canonical = clean_text(metadata.get("canonical_url"))
    site_url = clean_text(feed_info.get("site_url") or canonical or final_url)
    return {
        "ok": True,
        "url": url,
        "original_url": original_url,
        "unwrapped_url": url if url != original_url else "",
        "final_url": final_url,
        "content_type": content_type or metadata.get("content_type", ""),
        "title": title,
        "description": description,
        "excerpt": clean_text(metadata.get("excerpt"), 900),
        "image_url": clean_text(metadata.get("image_url")),
        "canonical_url": canonical,
        "source_name": host_label(final_url),
        "is_feed": bool(feed_info),
        "feed_title": clean_text(feed_info.get("feed_title"), 220),
        "feed_type": clean_text(feed_info.get("feed_type")),
        "entry_count": feed_info.get("entry_count", 0),
        "site_url": site_url,
        "feed_suggestions": enriched_feeds,
        "metadata_error": metadata_error,
        "document_error": document_error,
    }


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"warning: skip invalid JSONL {path}:{line_number}: {exc}", file=sys.stderr)
    return records


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_status_json(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.exists() and path.stat().st_size > 0
    if needs_newline:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def upsert_jsonl(path: Path, record: dict) -> None:
    record_id = record.get("id")
    if not record_id:
        append_jsonl(path, record)
        return
    records = load_jsonl(path)
    updated = []
    replaced = False
    for existing in records:
        if existing.get("id") == record_id:
            updated.append(record)
            replaced = True
        else:
            updated.append(existing)
    if not replaced:
        updated.append(record)
    write_jsonl(path, updated)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_time_label(dt: datetime | None = None) -> str:
    current = dt.astimezone(LOCAL_TIMEZONE) if dt else datetime.now(LOCAL_TIMEZONE)
    return f"{current.month:02d} 月 {current.day:02d} 日 {current.hour:02d} 時 {current.minute:02d} 分 {current.second:02d} 秒"


def data_commit_message(dt: datetime | None = None) -> str:
    return f"閱讀資料庫自訂紀錄 {local_time_label(dt)} 的更新"


def data_autocommit_file_labels() -> list[str]:
    return [str(path.relative_to(ROOT)) for path in DATA_AUTOCOMMIT_FILES]


def data_autocommit_status(state: str, message: str = "", **extra: object) -> dict:
    previous = load_json(DATA_COMMIT_STATUS)
    status = {
        "state": state,
        "message": message,
        "updated_at": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
        **extra,
    }
    if "next_run_at" not in status and previous.get("next_run_at"):
        status["next_run_at"] = previous.get("next_run_at")
    if "interval_seconds" not in status and previous.get("interval_seconds"):
        status["interval_seconds"] = previous.get("interval_seconds")
    write_status_json(DATA_COMMIT_STATUS, status)
    return status


def data_files_dirty() -> tuple[bool, str]:
    command = ["git", "status", "--porcelain", "--", *data_autocommit_file_labels()]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git status failed")
    return bool(result.stdout.strip()), result.stdout.strip()


def commit_database_state(trigger: str = "manual") -> dict:
    with DATA_AUTOCOMMIT_LOCK:
        started_at = datetime.now(LOCAL_TIMEZONE)
        data_autocommit_status(
            "running",
            "正在檢查閱讀資料庫是否需要 commit。",
            trigger=trigger,
            files=data_autocommit_file_labels(),
        )
        try:
            dirty, status_output = data_files_dirty()
            if not dirty:
                return data_autocommit_status(
                    "no-changes",
                    "閱讀資料庫目前沒有需要 commit 的變更。",
                    trigger=trigger,
                    files=data_autocommit_file_labels(),
                )

            labels = data_autocommit_file_labels()
            subprocess.run(["git", "add", "--", *labels], cwd=ROOT, check=True, text=True, capture_output=True, timeout=30)
            message = data_commit_message(started_at)
            commit = subprocess.run(
                ["git", "commit", "-m", message, "--", *labels],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=120,
            )
            output = commit.stdout + ("\nSTDERR:\n" + commit.stderr if commit.stderr else "")
            if commit.returncode != 0:
                return data_autocommit_status(
                    "failed",
                    "閱讀資料庫 commit 沒有成功。",
                    trigger=trigger,
                    files=labels,
                    git_status=status_output,
                    output=output,
                    returncode=commit.returncode,
                )
            rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, capture_output=True, timeout=20)
            commit_id = clean_text(rev.stdout)
            return data_autocommit_status(
                "committed",
                f"已送出閱讀資料庫自訂紀錄 commit {commit_id}。",
                trigger=trigger,
                files=labels,
                commit=commit_id,
                commit_message=message,
                git_status=status_output,
                output=output,
                returncode=0,
            )
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            return data_autocommit_status(
                "failed",
                f"閱讀資料庫 commit 發生錯誤：{exc}",
                trigger=trigger,
                files=data_autocommit_file_labels(),
            )


def start_data_autocommit_worker() -> None:
    def worker() -> None:
        while True:
            next_run = datetime.now(LOCAL_TIMEZONE) + timedelta(seconds=DATA_AUTOCOMMIT_INTERVAL_SECONDS)
            current = load_json(DATA_COMMIT_STATUS)
            if (current.get("state") or "") not in {"running", "committed", "failed", "no-changes"}:
                current = {}
            data_autocommit_status(
                current.get("state") or "idle",
                current.get("message") or "閱讀資料庫自動 commit 排程已啟動。",
                next_run_at=next_run.isoformat(timespec="seconds"),
                interval_seconds=DATA_AUTOCOMMIT_INTERVAL_SECONDS,
                files=data_autocommit_file_labels(),
            )
            time.sleep(DATA_AUTOCOMMIT_INTERVAL_SECONDS)
            commit_database_state("auto")

    threading.Thread(target=worker, name="data-autocommit", daemon=True).start()


def default_review(notes: str = "") -> dict:
    return {
        "angle": "",
        "research_status": "not-started",
        "structure_review": "pending",
        "line_review": "pending",
        "target_reader_review": "pending",
        "fact_check": "pending",
        "notes": notes,
    }


def form_value(data: dict[str, list[str]], key: str, default: str = "") -> str:
    return clean_text((data.get(key) or [default])[0])


def selected(value: str, current: str) -> str:
    return " selected" if value == current else ""


def option_list(options: list[tuple[str, str]] | list[str], current: str) -> str:
    rows = []
    for option in options:
        value, label = option if isinstance(option, tuple) else (option, option)
        rows.append(f'<option value="{h(value)}"{selected(value, current)}>{h(label)}</option>')
    return "\n".join(rows)


def track_meta(track: str) -> dict:
    return TRACK_META.get(track) or TRACK_META["unclassified"]


def track_label(track: str) -> str:
    return track_meta(track)["label"]


def track_class(track: str) -> str:
    return track_meta(track)["class"]


def source_type_label(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(source_type, source_type or "未標示")


def source_status_label(status: str) -> str:
    return SOURCE_STATUS_LABELS.get(status, status or "未標示")


def source_type_options(current: str) -> str:
    return option_list([(value, SOURCE_TYPE_LABELS.get(value, value)) for value in SOURCE_TYPES], current)


def source_status_options(current: str) -> str:
    return option_list([(value, SOURCE_STATUS_LABELS.get(value, value)) for value in SOURCE_STATUSES], current)


def source_frequency_label(frequency: str) -> str:
    return FETCH_FREQUENCY_LABELS.get(frequency or "daily", frequency or "每天抓")


def source_frequency_options(current: str) -> str:
    return option_list([(value, FETCH_FREQUENCY_LABELS.get(value, value)) for value in FETCH_FREQUENCIES], current or "daily")


def form_lines(value: object) -> list[str]:
    if isinstance(value, list):
        raw_lines = [str(line) for line in value]
    else:
        raw_lines = re.split(r"[\n,，]", str(value or ""))
    return [line.strip() for line in raw_lines if line.strip()]


def source_keywords_text(source: dict, key: str) -> str:
    return "\n".join(form_lines(source.get(key)))


def source_keyword_signature(source: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(form_lines(source.get("required_keywords"))),
        tuple(form_lines(source.get("excluded_keywords"))),
    )


def source_keyword_haystack(record: dict) -> str:
    parts: list[str] = []
    for key in ["title", "summary", "url", "source_name", "author", "published_at", "captured_at"]:
        parts.append(clean_text(record.get(key)))
    for value in [record.get("tags"), record.get("keywords")]:
        if isinstance(value, list):
            parts.extend(clean_text(item) for item in value)
        else:
            parts.append(clean_text(value))
    for section_key in ["reference", "triage", "editorial_triage", "reading_metadata"]:
        section = record.get(section_key)
        if not isinstance(section, dict):
            continue
        for key in ["title", "summary", "description", "recommendation", "content_kind", "url", "site_name"]:
            parts.append(clean_text(section.get(key)))
    return "\n".join(part for part in parts if part).casefold()


def source_keyword_matches(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if clean_text(keyword).casefold() in text]


def source_record_passes_keywords(record: dict, source: dict) -> bool:
    required = form_lines(source.get("required_keywords"))
    excluded = form_lines(source.get("excluded_keywords"))
    if not required and not excluded:
        return True
    haystack = source_keyword_haystack(record)
    if source_keyword_matches(haystack, excluded):
        return False
    if required and not source_keyword_matches(haystack, required):
        return False
    return True


def is_fetchable_source(source: dict) -> bool:
    return (
        source.get("status") == "active"
        and source.get("fetch_frequency", "daily") != "paused"
        and source.get("track") in {"digital-humanities-local-knowledge", "open-tech-open-industry"}
        and source.get("source_type") in {"rss", "google-alert", "youtube", "podcast"}
    )


def count_items(items: list[dict], track: str, status: str | None = None) -> int:
    return sum(1 for item in items if item.get("track") == track and (status is None or item.get("status") == status))


def count_sources(sources: list[dict], track: str, active_only: bool = False) -> int:
    return sum(
        1
        for source in sources
        if source.get("track") == track
        and source.get("status") != "archived"
        and (not active_only or is_fetchable_source(source))
    )


def safe_redirect_path(value: object, default: str = "/sources") -> str:
    path = clean_text(value)
    if not path or not path.startswith("/") or path.startswith("//"):
        return default
    return path


def source_name_link(item: dict) -> str:
    name = h(item.get("source_name") or item.get("author") or "未標示來源")
    source_id = clean_text(item.get("source_id"))
    if not source_id:
        return name
    return f'<a href="/sources/view?id={quote(source_id)}">{name}</a>'


def parse_loose_date(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        number = float(text)
        if 20000 <= number <= 60000:
            return datetime.fromordinal((datetime(1899, 12, 30).toordinal() + int(number))).replace(tzinfo=timezone.utc)
    normalized = text.replace("Z", "+00:00").replace("/", "-")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    match = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", normalized)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def latest_record_date(records: list[dict]) -> str:
    dates = [
        parsed
        for record in records
        for parsed in [parse_loose_date(record.get("dismissed_at") or record.get("captured_at") or record.get("published_at"))]
        if parsed
    ]
    if not dates:
        return ""
    return max(dates).date().isoformat()


def item_datetime(item: dict, *keys: str) -> datetime | None:
    for key in keys or ("published_at", "captured_at", "dismissed_at"):
        parsed = parse_loose_date(item.get(key))
        if parsed:
            return parsed
    return None


def format_datetime(value: object, fallback: str = "未標示時間") -> str:
    parsed = parse_loose_date(value)
    if not parsed:
        text = clean_text(value)
        return text or fallback
    local = parsed.astimezone()
    if local.hour == 0 and local.minute == 0 and local.second == 0:
        return local.strftime("%Y-%m-%d")
    return local.strftime("%Y-%m-%d %H:%M")


def item_display_time(item: dict, *keys: str) -> str:
    for key in keys or ("published_at", "captured_at", "dismissed_at"):
        text = clean_text(item.get(key))
        if text:
            return format_datetime(text)
    return "未標示時間"


def item_sort_time(item: dict) -> str:
    parsed = item_datetime(item, "published_at", "captured_at", "dismissed_at")
    return parsed.isoformat() if parsed else ""


def parse_local_date_input(value: str, *, end: bool = False) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        date_value = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None
    parsed = datetime(date_value.year, date_value.month, date_value.day, tzinfo=LOCAL_TIMEZONE)
    return parsed + timedelta(days=1) if end else parsed


def reader_time_bounds(time_filter: str, start_value: str = "", end_value: str = "") -> tuple[datetime | None, datetime | None]:
    now = datetime.now(LOCAL_TIMEZONE)
    if time_filter == "three-days":
        return now - timedelta(days=3), None
    if time_filter == "week":
        return now - timedelta(days=7), None
    if time_filter == "month":
        return now - timedelta(days=30), None
    if time_filter == "quarter":
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        return datetime(now.year, quarter_month, 1, tzinfo=LOCAL_TIMEZONE), None
    if time_filter == "year":
        return datetime(now.year, 1, 1, tzinfo=LOCAL_TIMEZONE), None
    if time_filter == "custom":
        return parse_local_date_input(start_value), parse_local_date_input(end_value, end=True)
    return None, None


def item_matches_time_filter(item: dict, start: datetime | None, end: datetime | None) -> bool:
    if not start and not end:
        return True
    parsed = item_datetime(item, "published_at", "captured_at", "dismissed_at")
    if not parsed:
        return False
    return (not start or parsed >= start) and (not end or parsed < end)


def reader_time_summary(time_filter: str, start_value: str = "", end_value: str = "") -> str:
    labels = dict(READER_TIME_FILTERS)
    if time_filter == "custom":
        start_text = clean_text(start_value) or "不限開始"
        end_text = clean_text(end_value) or "不限結束"
        return f"自定時間範圍：{start_text} 至 {end_text}"
    return labels.get(time_filter, labels["all"])


def source_health_summary(source: dict, items: list[dict], rejected: list[dict], candidates: list[dict], dismissed: list[dict]) -> dict:
    source_id = source.get("id")
    source_items = [item for item in items if item.get("source_id") == source_id]
    source_rejected = [item for item in rejected if item.get("source_id") == source_id]
    source_candidates = [item for item in candidates if item.get("source_id") == source_id]
    source_dismissed = [item for item in dismissed if item.get("source_id") == source_id]
    accepted = sum(1 for item in source_items if is_reader_item(item) or item.get("status") in {"triaged", "ready", "published"})
    inbox = sum(1 for item in source_items if item.get("status") == "inbox")
    rejected_count = len(source_rejected) + len(source_dismissed)
    candidate_count = len(source_candidates)
    rss_health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
    saved_assessment = source.get("health_assessment") if isinstance(source.get("health_assessment"), dict) else {}
    keyword_skips = int(rss_health.get("skipped_source_keywords") or 0)
    duplicate_skips = int(rss_health.get("skipped_duplicate_recent") or 0)
    last_status = clean_text(rss_health.get("last_fetch_status"))
    recommendation = clean_text(saved_assessment.get("recommendation"))
    if source.get("status") == "archived":
        level = "archived"
        label = "已封存"
        reason = "這個來源目前不在日常追蹤清單。"
    elif last_status == "failed":
        level = "danger"
        label = "抓取失敗"
        reason = clean_text(rss_health.get("last_error"), 120) or "最近一次 RSS 抓取沒有成功。"
    elif recommendation:
        level = clean_text(saved_assessment.get("level")) or "watch"
        label = recommendation
        reason = clean_text(saved_assessment.get("reason"), 180)
    elif rejected_count >= 5 and rejected_count >= max(accepted * 2, 3):
        level = "danger"
        label = "建議暫停或重設篩選"
        reason = f"已不收 {rejected_count} 次，明顯高於收下 {accepted} 次。"
    elif keyword_skips >= 10 and keyword_skips >= max(int(rss_health.get("new_items") or 0) * 3, 10):
        level = "watch"
        label = "個別關鍵字偏嚴"
        reason = f"最近抓取有 {keyword_skips} 則被來源關鍵字擋下。"
    elif duplicate_skips >= 10:
        level = "watch"
        label = "重複偏多"
        reason = f"最近抓取有 {duplicate_skips} 則是近 7 天已看過的網址。"
    elif accepted >= 3 and accepted >= rejected_count:
        level = "healthy"
        label = "健康"
        reason = f"已收下 {accepted} 則，和目前不收比例相比仍值得追。"
    elif accepted == 0 and rejected_count == 0 and candidate_count == 0 and inbox == 0:
        level = "new"
        label = "新來源 / 待觀察"
        reason = "目前還沒有足夠的收錄或不收紀錄。"
    else:
        level = "watch"
        label = "觀察中"
        reason = f"收下 {accepted}，待整理 {inbox + candidate_count}，不收 {rejected_count}。"
    return {
        "level": level,
        "label": label,
        "reason": reason,
        "accepted": accepted,
        "inbox": inbox,
        "candidates": candidate_count,
        "rejected": rejected_count,
        "keyword_skips": keyword_skips,
        "duplicate_skips": duplicate_skips,
        "last_seen": latest_record_date([*source_items, *source_rejected, *source_candidates, *source_dismissed]),
        "last_checked_at": clean_text(rss_health.get("last_checked_at") or saved_assessment.get("generated_at")),
    }


def source_health_badge(summary: dict) -> str:
    level_class = {
        "healthy": "suggest-keep",
        "watch": "neutral",
        "new": "neutral",
        "danger": "suggest-skip",
        "archived": "archived",
    }.get(summary.get("level"), "neutral")
    return badge(summary.get("label") or "觀察中", level_class)


def badge(label: str, class_name: str = "neutral") -> str:
    return f'<span class="badge badge--{h(class_name)}">{h(label)}</span>'


def href_with_query(path: str, params: list[tuple[str, str]]) -> str:
    clean_params = [(key, value) for key, value in params if value]
    if not clean_params:
        return path
    return path + "?" + urlencode(clean_params)


def metric_card(value: object, label: str, href: str = "", hint: str = "", class_name: str = "") -> str:
    classes = "card metric-card"
    if class_name:
        classes += f" {class_name}"
    hint_html = f'<span class="metric-link-label">{h(hint)}</span>' if hint else ""
    value_html = h(str(value)) if value is not None else ""
    content = f'<div class="metric">{value_html}</div><div class="metric-label">{h(label)}</div>{hint_html}'
    if href:
        return f'<a class="{h(classes)}" href="{h(href)}">{content}</a>'
    return f'<div class="{h(classes)}">{content}</div>'


def metric_tile(value: object, label: str, href: str = "", hint: str = "", class_name: str = "") -> str:
    classes = "metric-tile"
    if class_name:
        classes += f" {class_name}"
    hint_html = f'<span class="metric-link-label">{h(hint)}</span>' if hint else ""
    value_html = h(str(value)) if value is not None else ""
    content = f'<div class="metric">{value_html}</div><div class="metric-label">{h(label)}</div>{hint_html}'
    if href:
        return f'<a class="{h(classes)}" href="{h(href)}">{content}</a>'
    return f'<div class="{h(classes)}">{content}</div>'


def command_card(name: str, config: dict) -> str:
    icon = COMMAND_ICONS.get(name, "read")
    shortcut = COMMAND_SHORTCUTS.get(name, "")
    return (
        "<div class='card command-card'>"
        f"<strong>{icon_span(icon, shortcut)}{h(config['label'])}</strong>"
        f"<p class='muted'>{h(config['description'])}</p>"
        "<form method='post' action='/commands/run' data-command-form>"
        f"<input type='hidden' name='command' value='{h(name)}'>"
        f"<button type='submit' class='secondary'>{button_content(config['button'], icon, shortcut)}</button>"
        "</form>"
        "</div>"
    )


def remove_local_candidate_fields(record: dict) -> dict:
    item = dict(record)
    item.pop("candidate_status", None)
    return item


def record_codex_review(record: dict) -> dict:
    editorial = record.get("editorial_triage") or {}
    if not isinstance(editorial, dict):
        return {}
    review = editorial.get("codex_review")
    return review if isinstance(review, dict) else {}


def candidate_recommendation(candidate: dict) -> str:
    codex_review = record_codex_review(candidate)
    if codex_review:
        codex_recommendation = clean_text(codex_review.get("recommendation")).casefold()
        if codex_recommendation == "recommend-skip":
            return "suggest-skip"
        return "suggest-keep"
    return (candidate.get("triage") or {}).get("recommendation", "unknown")


def is_skill_candidate(item: dict) -> bool:
    decision = item.get("local_decision") or {}
    return item.get("status") == "triaged" and (
        decision.get("action") == "accepted-for-editing"
        or decision.get("next_step") == "run-writing-skill-before-pr"
    )


def is_direct_pr_item(item: dict) -> bool:
    decision = item.get("local_decision") or {}
    return item.get("status") == "ready" and decision.get("action") == "direct-pr-small-news"


def item_display_kind(item: dict) -> str:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    explicit_kind = clean_text(item.get("content_kind") or editorial.get("content_kind"))
    tags = {clean_text(tag) for tag in item.get("tags", []) if clean_text(tag)}
    if explicit_kind in {"opinion", "opinion-article"} or "觀點文章" in tags:
        return "opinion-article"
    if is_skill_candidate(item):
        return "featured-article"
    if is_direct_pr_item(item) or item.get("status") == "ready":
        return "small-news"
    editorial = item.get("editorial_triage") or {}
    if isinstance(editorial, dict) and editorial.get("content_kind") == "small-news":
        return "small-news"
    return "needs-review"


def item_triage_keywords(item: dict) -> set[str]:
    triage = item.get("triage") or {}
    keywords = set(triage.get("matched_keywords") or [])
    keywords.update(triage.get("skip_keywords") or [])
    return {str(keyword) for keyword in keywords if str(keyword).strip()}


def recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-keep":
        return "建議收"
    if recommendation == "suggest-skip":
        return "建議不要看"
    return "未判斷"


def editorial_recommendation_label(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "建議收錄"
    if recommendation == "suggest-review":
        return "建議人工看過"
    if recommendation == "suggest-skip":
        return "建議不要看"
    return "尚未初篩"


def content_kind_label(kind: str) -> str:
    if kind in {"opinion", "opinion-article"}:
        return "觀點文章"
    if kind == "featured-article":
        return "精選文章 / 待跑 skill"
    if kind == "small-news":
        return "純新聞 / 小消息"
    return "人工判斷"


def status_label(status: str) -> str:
    labels = {
        "inbox": "待整理",
        "triaged": "待跑 skill",
        "researching": "補來源中",
        "drafting": "撰稿中",
        "reviewing": "審稿中",
        "fact-checking": "查核中",
        "ready": "可送 PR / 可讀",
        "published": "已發布",
        "archived": "封存",
    }
    return labels.get(status, status or "未標示")


def editorial_badge_class(recommendation: str) -> str:
    if recommendation == "suggest-collect":
        return "suggest-keep"
    if recommendation == "suggest-review":
        return "neutral"
    if recommendation == "suggest-skip":
        return "suggest-skip"
    return "neutral"


def item_detail_href(item: dict) -> str:
    return f"/items/view?id={quote(str(item.get('id', '')))}"


def resolve_final_url(url: str, timeout: int = 12) -> tuple[str, str]:
    url = unwrap_google_alert_url(clean_text(url))
    if not url:
        return "", "網址是空的。"
    headers = {"User-Agent": "IanOpenNewsBot/1.0 (+https://github.com/)"}
    for method in ["HEAD", "GET"]:
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.geturl(), ""
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in {403, 405, 501}:
                continue
            return "", str(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if method == "HEAD":
                continue
            return "", str(exc)
    return "", "無法解析跳轉網址。"


def personal_note_text(item: dict) -> str:
    notes = item.get("personal_notes")
    if isinstance(notes, dict):
        return clean_text(notes.get("body"))
    return clean_text(notes)


def looks_like_triage_placeholder(text: str) -> bool:
    normalized = clean_text(text, 1200)
    if not normalized:
        return False
    if "中文標題：" in normalized and "中文摘要：" in normalized:
        return True
    if normalized.startswith("這是一篇英文資料，主題可能和"):
        return True
    return False


def item_original_summary(item: dict, limit: int = 420) -> str:
    metadata = item_reading_metadata(item)
    candidates = [
        item.get("summary"),
        metadata.get("description"),
        metadata.get("excerpt"),
        metadata.get("og_description"),
        metadata.get("twitter_description"),
    ]
    for candidate in candidates:
        text = clean_text(candidate, limit)
        if text and not looks_like_triage_placeholder(text):
            return text
    editorial = item.get("editorial_triage") or {}
    if isinstance(editorial, dict):
        text = clean_text(editorial.get("zh_summary"), limit)
        if text and not looks_like_triage_placeholder(text):
            return text
    return ""


def item_zh_summary(item: dict, limit: int = 420) -> str:
    editorial = item.get("editorial_triage") or {}
    if isinstance(editorial, dict):
        codex_review = editorial.get("codex_review")
        if isinstance(codex_review, dict):
            text = clean_text(codex_review.get("summary")) or clean_text(codex_review.get("one_line_recommendation"))
            if text:
                return clean_text(text, limit)
    return item_original_summary(item, limit)


def item_codex_review(item: dict) -> dict:
    return record_codex_review(item)


def item_reading_metadata(item: dict) -> dict:
    metadata = item.get("reading_metadata")
    return metadata if isinstance(metadata, dict) else {}


def item_codex_zh_title(item: dict) -> str:
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    codex_review = editorial.get("codex_review") if isinstance(editorial.get("codex_review"), dict) else {}
    return (
        clean_text(codex_review.get("zh_title"), 300)
        or clean_text(editorial.get("zh_title"), 300)
        or clean_text(editorial.get("codex_zh_title"), 300)
    )


def item_display_title(item: dict) -> str:
    metadata = item_reading_metadata(item)
    return (
        clean_text(item.get("editorial_title"), 320)
        or clean_text(metadata.get("editorial_title"), 320)
        or item_codex_zh_title(item)
        or clean_text(metadata.get("translated_zh_title"), 320)
        or clean_text(item.get("title"), 320)
        or clean_text(item.get("url"), 320)
        or "未命名項目"
    )


def item_original_title(item: dict) -> str:
    metadata = item_reading_metadata(item)
    return clean_text(metadata.get("original_site_title") or metadata.get("title") or item.get("title"), 360)


def language_label(language: object) -> str:
    code = clean_text(language, 80)
    labels = {
        "zh": "中文",
        "zh-Hant": "繁體中文",
        "zh-Hans": "簡體中文",
        "en": "英文",
        "ja": "日文",
        "ko": "韓文",
        "fr": "法文",
        "de": "德文",
        "es": "西班牙文",
        "pt": "葡萄牙文",
    }
    return labels.get(code, code or "未知")


def metadata_source_label(metadata: dict, field: str) -> str:
    source = clean_text(metadata.get(f"{field}_source"), 120)
    if not source:
        return ""
    return f"（{source}）"


def item_original_language(item: dict) -> str:
    metadata = item_reading_metadata(item)
    language = clean_text(metadata.get("original_language"))
    if language:
        return language
    text = "\n".join(
        part
        for part in [
            item_article_text(item),
            clean_text(metadata.get("article_markdown"), 3000),
            clean_text(item.get("summary"), 1200),
            clean_text(item.get("title"), 300),
        ]
        if part
    )
    return infer_language_from_text(text)


def is_foreign_language_item(item: dict) -> bool:
    language = item_original_language(item)
    if not language or language in {"unknown", "und"}:
        return False
    return not language.startswith("zh")


def item_translated_markdown(item: dict) -> str:
    return clean_text(item_reading_metadata(item).get("translated_article_markdown_zh"))


def item_article_text(item: dict) -> str:
    return clean_text(item_reading_metadata(item).get("article_text"))


def item_article_markdown(item: dict) -> str:
    metadata = item_reading_metadata(item)
    markdown = clean_text(metadata.get("article_markdown"))
    if markdown:
        return markdown
    article_text = clean_text(metadata.get("article_text"))
    if article_text:
        return text_to_markdown(article_text, title=metadata.get("title") or item.get("title") or "")
    return ""


def inline_markdown_html(text: str) -> str:
    def format_segment(segment: str) -> str:
        escaped = h(segment)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
        return escaped

    parts: list[str] = []
    position = 0
    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
        parts.append(format_segment(text[position : match.start()]))
        label = format_segment(match.group(1))
        url = h(match.group(2))
        parts.append(f'<a href="{url}" target="_blank" rel="noreferrer">{label}</a>')
        position = match.end()
    parts.append(format_segment(text[position:]))
    return "".join(parts)


def markdown_to_html(markdown: str) -> str:
    raw = html.unescape(str(markdown or ""))
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[ \t\f\v]+", " ", raw)
    raw = re.sub(r"\n[ \t]+", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw).strip()
    lines = raw.split("\n")
    parts: list[str] = []
    paragraph: list[str] = []
    list_tag = ""

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            parts.append(f"</{list_tag}>")
            list_tag = ""

    def flush_paragraph() -> None:
        if paragraph:
            parts.append(f"<p>{inline_markdown_html(' '.join(paragraph))}</p>")
            paragraph.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)), 3)
            parts.append(f"<h{level}>{inline_markdown_html(heading.group(2))}</h{level}>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            close_list()
            parts.append(f"<blockquote>{inline_markdown_html(line[2:])}</blockquote>")
            continue
        unordered = re.match(r"^[-*]\s+(.+)$", line)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            target_tag = "ul" if unordered else "ol"
            if list_tag != target_tag:
                close_list()
                parts.append(f"<{target_tag}>")
                list_tag = target_tag
            item_text = (unordered or ordered).group(1)
            parts.append(f"<li>{inline_markdown_html(item_text)}</li>")
            continue
        close_list()
        paragraph.append(line)

    flush_paragraph()
    close_list()
    return "\n".join(parts) or "<p>這次沒有抓到可顯示的主文。</p>"


def item_article_html(item: dict) -> str:
    return markdown_to_html(item_article_markdown(item))


def ensure_article_markdown(item: dict) -> tuple[dict, bool]:
    metadata = item_reading_metadata(item)
    if metadata.get("article_markdown") or not metadata.get("article_text"):
        return item, False
    markdown = text_to_markdown(metadata.get("article_text"), title=metadata.get("title") or item.get("title") or "")
    if not markdown:
        return item, False
    updated = dict(item)
    updated_metadata = dict(metadata)
    updated_metadata.update(
        {
            "article_markdown": markdown,
            "article_markdown_chars": len(markdown),
            "article_markdown_method": f"{metadata.get('article_text_method', 'text')}.markdown",
            "article_markdown_status": "ok" if len(markdown) >= 280 else "short",
            "article_markdown_label": "Markdown 閱讀版",
        }
    )
    updated["reading_metadata"] = updated_metadata
    return updated, True


def item_cached_image_url(item: dict) -> str:
    metadata = item_reading_metadata(item)
    cache = metadata.get("image_cache")
    if not isinstance(cache, dict):
        return ""
    local_path = clean_text(cache.get("path"))
    reader_url = clean_text(cache.get("reader_url"))
    if local_path and (ROOT / local_path).exists():
        if reader_url:
            return "/" + reader_url.lstrip("/")
        if local_path.startswith("docs/reader/"):
            return "/" + local_path.removeprefix("docs/").lstrip("/")
    return ""


def item_image_url(item: dict) -> str:
    cached = item_cached_image_url(item)
    if cached:
        return cached
    candidates = [
        item.get("image"),
        item.get("image_url"),
        item.get("thumbnail"),
    ]
    reference = item.get("reference") or {}
    reading_metadata = item.get("reading_metadata") or {}
    if isinstance(reading_metadata, dict):
        candidates.extend(
            [
                reading_metadata.get("image_url"),
                reading_metadata.get("og_image"),
                reading_metadata.get("twitter_image"),
            ]
        )
    if isinstance(reference, dict):
        candidates.extend(
            [
                reference.get("image"),
                reference.get("image_url"),
                reference.get("thumbnail"),
                reference.get("og_image"),
            ]
        )
        raw_columns = reference.get("raw_columns")
        if isinstance(raw_columns, dict):
            candidates.extend(
                [
                    raw_columns.get("image"),
                    raw_columns.get("Image"),
                    raw_columns.get("圖片"),
                    raw_columns.get("封面"),
                ]
            )
    summary = str(item.get("summary") or "")
    candidates.extend(re.findall(r"""<img[^>]+src=["']([^"']+)["']""", summary, flags=re.I))
    candidates.extend(re.findall(r"""https?://[^\s"'<>]+?\.(?:png|jpe?g|webp)(?:\?[^\s"'<>]*)?""", summary, flags=re.I))
    for candidate in candidates:
        value = clean_text(candidate)
        if value.startswith(("http://", "https://")):
            return value
    return ""


LAYOUT_MODES = ["card", "list", "compact"]
READER_TIME_FILTERS = [
    ("three-days", "這三天（-3 天）"),
    ("week", "這一週"),
    ("month", "這一個月（-30 天）"),
    ("quarter", "這一季"),
    ("year", "這一年"),
    ("custom", "自定時間範圍"),
    ("all", "全部"),
]


def layout_icon(mode: str) -> str:
    icons = {
        "card": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="7" height="7" rx="1.5"></rect><rect x="13" y="4" width="7" height="7" rx="1.5"></rect><rect x="4" y="13" width="7" height="7" rx="1.5"></rect><rect x="13" y="13" width="7" height="7" rx="1.5"></rect></svg>',
        "list": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="5" rx="1.5"></rect><rect x="4" y="14" width="16" height="5" rx="1.5"></rect></svg>',
        "compact": '<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="8" y1="6" x2="20" y2="6"></line><line x1="8" y1="12" x2="20" y2="12"></line><line x1="8" y1="18" x2="20" y2="18"></line><circle cx="4" cy="6" r="1.5"></circle><circle cx="4" cy="12" r="1.5"></circle><circle cx="4" cy="18" r="1.5"></circle></svg>',
    }
    return icons.get(mode, icons["list"])


def layout_label(mode: str) -> str:
    return {"card": "卡片", "list": "列表", "compact": "清單"}.get(mode, "列表")


def action_icon(action: str) -> str:
    icons = {
        "read": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"></path><path d="M8 7h8"></path><path d="M8 11h7"></path></svg>',
        "expand": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5"></path><path d="M3 3l7 7"></path><path d="M16 21h5v-5"></path><path d="M21 21l-7-7"></path></svg>',
        "external": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7"></path><path d="M21 3l-9 9"></path><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"></path></svg>',
        "wand": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 4V2"></path><path d="M15 16v-2"></path><path d="M8 9H6"></path><path d="M20 9h-2"></path><path d="M17.8 6.2l1.4-1.4"></path><path d="M10.8 13.2l-7 7a1.5 1.5 0 0 0 2.1 2.1l7-7"></path><path d="M12 8l4 4"></path></svg>',
        "home": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11l9-8 9 8"></path><path d="M5 10v10h14V10"></path><path d="M9 20v-6h6v6"></path></svg>',
        "globe": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M3 12h18"></path><path d="M12 3a14 14 0 0 1 0 18"></path><path d="M12 3a14 14 0 0 0 0 18"></path></svg>',
        "archive": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16"></path><path d="M6 7v13h12V7"></path><path d="M4 4h16v3H4z"></path><path d="M9 11h6"></path></svg>',
        "workspace": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="14" rx="2"></rect><path d="M8 20h8"></path><path d="M12 18v2"></path><path d="M7 8h5"></path><path d="M7 12h10"></path></svg>',
        "rss": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5a14 14 0 0 1 14 14"></path><path d="M5 11a8 8 0 0 1 8 8"></path><circle cx="6" cy="18" r="1.5"></circle></svg>',
        "inbox": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 13l2-7h12l2 7"></path><path d="M4 13v5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5h-5a3 3 0 0 1-6 0z"></path></svg>',
        "plus": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14"></path><path d="M5 12h14"></path></svg>',
        "settings": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"></path><path d="M4 12h2"></path><path d="M18 12h2"></path><path d="M12 4v2"></path><path d="M12 18v2"></path><path d="M6.3 6.3l1.4 1.4"></path><path d="M16.3 16.3l1.4 1.4"></path><path d="M17.7 6.3l-1.4 1.4"></path><path d="M7.7 16.3l-1.4 1.4"></path></svg>',
        "filter": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16"></path><path d="M7 12h10"></path><path d="M10 19h4"></path></svg>',
        "source": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13"></path><path d="M8 12h13"></path><path d="M8 18h13"></path><circle cx="4" cy="6" r="1.5"></circle><circle cx="4" cy="12" r="1.5"></circle><circle cx="4" cy="18" r="1.5"></circle></svg>',
        "check-circle": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M8 12l2.5 2.5L16 9"></path></svg>',
        "pulse": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h4l2-7 4 14 2-7h6"></path></svg>',
        "database": '<svg viewBox="0 0 24 24" aria-hidden="true"><ellipse cx="12" cy="5" rx="7" ry="3"></ellipse><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5"></path><path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"></path></svg>',
        "publish": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4"></path><path d="M7 9l5-5 5 5"></path><path d="M5 20h14"></path></svg>',
        "image": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"></rect><circle cx="8" cy="10" r="1.5"></circle><path d="M21 16l-5-5-4 4-2-2-5 5"></path></svg>',
        "text-lines": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 6h14"></path><path d="M5 10h14"></path><path d="M5 14h10"></path><path d="M5 18h12"></path></svg>',
        "sparkle": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"></path><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"></path></svg>',
        "branch": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="6" r="2"></circle><circle cx="18" cy="6" r="2"></circle><circle cx="12" cy="18" r="2"></circle><path d="M8 6h8"></path><path d="M6 8v2a8 8 0 0 0 6 7.7"></path><path d="M18 8v2a8 8 0 0 1-6 7.7"></path></svg>',
        "chart": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5"></path><path d="M4 19h16"></path><rect x="7" y="11" width="3" height="5"></rect><rect x="12" y="8" width="3" height="8"></rect><rect x="17" y="6" width="3" height="10"></rect></svg>',
        "save": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h12l2 2v14H5z"></path><path d="M8 4v6h8V4"></path><path d="M8 20v-6h8v6"></path></svg>',
        "accept": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l4 4L19 6"></path><path d="M5 20h14"></path></svg>',
        "small-news": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2"></rect><path d="M8 9h8"></path><path d="M8 13h5"></path><path d="M8 17h8"></path></svg>',
        "reject": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M8 8l8 8"></path><path d="M16 8l-8 8"></path></svg>',
        "select": '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"></rect><path d="M8 12l3 3 5-6"></path></svg>',
        "clear": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12"></path><path d="M18 6L6 18"></path></svg>',
        "preview": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
        "refresh": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5"></path><path d="M4 18v-5h5"></path><path d="M19 11a7 7 0 0 0-12-4"></path><path d="M5 13a7 7 0 0 0 12 4"></path></svg>',
        "edit": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11a2.5 2.5 0 0 0-4-4L4 16z"></path><path d="M13 6l5 5"></path></svg>',
        "translate": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h10"></path><path d="M9 5v14"></path><path d="M4 19h10"></path><path d="M16 10h4l-2 8"></path><path d="M15 18h6"></path></svg>',
        "note": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14v16H5z"></path><path d="M8 8h8"></path><path d="M8 12h8"></path><path d="M8 16h5"></path></svg>',
    }
    return icons.get(action, icons["read"])


def icon_span(action: str, shortcut: str = "", class_name: str = "icon") -> str:
    shortcut = clean_text(shortcut, 8).upper()
    shortcut_html = f'<span class="shortcut-hint">⌥{h(shortcut)}</span>' if shortcut else ""
    shortcut_attr = f' data-shortcut="{h(shortcut)}"' if shortcut else ""
    return f'<span class="{h(class_name)}" aria-hidden="true"{shortcut_attr}>{action_icon(action)}{shortcut_html}</span>'


def button_content(label: str, action: str, shortcut: str = "") -> str:
    return f'{icon_span(action, shortcut)}<span>{h(label)}</span>'


def action_label(label: str) -> str:
    return f'<span class="reader-action-label">{h(label)}</span>'


def layout_toggle(section_id: str, current: str = "list") -> str:
    current = current if current in LAYOUT_MODES else "list"
    buttons = []
    for mode in LAYOUT_MODES:
        active = " is-active" if mode == current else ""
        buttons.append(
            f"""
<button type="button" class="layout-toggle-button{active}" data-layout-target="{h(section_id)}" data-layout-mode="{h(mode)}" aria-pressed="{str(mode == current).lower()}" title="{h(layout_label(mode))}">
  {layout_icon(mode)}
  <span>{h(layout_label(mode))}</span>
</button>
"""
        )
    return f'<div class="layout-toggle" role="group" aria-label="顯示模式">{"".join(buttons)}</div>'


def is_reader_item(item: dict) -> bool:
    if item.get("status") in {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}:
        return True
    decision = item.get("local_decision") or {}
    return isinstance(decision, dict) and decision.get("action") in {"accepted-for-editing", "direct-pr-small-news"}


def editorial_triage_html(item: dict, compact: bool = False, reject_action: str = "/items/reject") -> str:
    editorial = item.get("editorial_triage") or {}
    if not isinstance(editorial, dict):
        editorial = {}
    recommendation = editorial.get("recommendation", "")
    kind = editorial.get("content_kind", "")
    confidence = editorial.get("confidence", "")
    if not editorial:
        return "<p class='help'>自動規則判斷：尚未重跑。可到首頁或關鍵字頁按「重新跑本機規則/關鍵字初篩」。</p>"
    display_kind = item_display_kind(item)
    codex_review = item_codex_review(item)
    codex_html = ""
    if codex_review:
        one_line = clean_text(codex_review.get("one_line_recommendation"), 420)
        summary = clean_text(codex_review.get("summary"), 900)
        reasons = codex_review.get("reasons") or []
        reason_rows = "<ol class='reason-list'>" + "".join(f"<li>{h(reason)}</li>" for reason in reasons[:3]) + "</ol>" if reasons and not compact else ""
        summary_html = f"<p class='zh-summary'>{h(summary)}</p>" if summary and not compact else ""
        codex_html = (
            "<div class='source-card source-card--model'>"
            "<div class='section-kicker'>Codex 生成</div>"
            "<h3>給 Ian 的閱讀建議</h3>"
            f"{badge('來源：Codex', 'suggest-keep')}"
            f"{badge('依主文生成' if codex_review.get('used_article_text') else '依既有資料生成', 'neutral')}"
            f"{badge(str(codex_review.get('generated_at', '')), 'neutral') if codex_review.get('generated_at') and not compact else ''}"
            f"<p class='recommendation-line'>{h(one_line)}</p>"
            f"{reason_rows}"
            f"{summary_html}"
            "</div>"
        )
    elif not compact:
        has_article_text = bool(item_article_text(item))
        button_label = "生成 Codex 建議" if has_article_text else "抓全文並生成 Codex 建議"
        codex_html = (
            "<div class='source-card source-card--model source-card--empty'>"
            "<div class='section-kicker'>Codex 生成</div>"
            "<h3>給 Ian 的閱讀建議</h3>"
            "<p class='help'>這則還沒有 Codex 生成摘要。可以直接在本頁補上；系統會先嘗試抓全文，再用目前可讀資料生成閱讀建議。</p>"
            "<form method='post' action='/items/codex-review' data-codex-review-form>"
            f"<input type='hidden' name='id' value='{h(item.get('id'))}'>"
            f"<input type='hidden' name='redirect' value='{h(item_detail_href(item))}'>"
            "<input type='hidden' name='with_fulltext' value='1'>"
            f"<button type='submit' class='secondary'>{button_content(button_label, 'sparkle', 'C')}</button>"
            "</form>"
            "</div>"
        )

    article_text = item_article_text(item)
    metadata = item_reading_metadata(item)
    source_text = article_text or clean_text(metadata.get("excerpt"), 900) or clean_text(item.get("summary"), 900)
    source_label = "原始主文" if article_text else "RSS/頁面摘要"
    source_html = ""
    if not compact:
        source_html = (
            "<div class='source-card source-card--source'>"
            f"<div class='section-kicker'>{h(source_label)}</div>"
            "<h3>本來文章的內容</h3>"
            f"{badge('已抓主文' if article_text else '尚未抓全文', 'neutral')}"
            f"{badge(str(metadata.get('article_text_method', 'metadata')), 'neutral') if metadata else ''}"
            f"<p class='source-excerpt'>{h(clean_text(source_text, 900))}</p>"
            "</div>"
        )

    reasons = editorial.get("view_reasons") or []
    reason_rows = ""
    if reasons and not compact:
        reason_rows = "<ol class='reason-list'>" + "".join(f"<li>{h(reason)}</li>" for reason in reasons[:3]) + "</ol>"
    deletion = editorial.get("deletion_pattern_fit") or {}
    deletion_signals = deletion.get("signals") or []
    deletion_html = ""
    if recommendation == "suggest-skip" and deletion_signals and not compact:
        deletion_html = f"<p class='help'>不要看的線索：{h('；'.join(deletion_signals[:3]))}</p>"
    reject_reason_html = ""
    suggested_reasons = suggested_rejection_reasons(item)
    if suggested_reasons and not compact:
        reject_reason_html = (
            "<p class='help'>建議不收分類</p>"
            f"<div class='reason-presets'>{inline_reject_buttons(clean_text(item.get('id')), suggested_reasons, limit=4, action=reject_action)}</div>"
        )
    zh_summary = clean_text(editorial.get("zh_summary"), 620)
    zh_summary_html = f"<p class='zh-summary'>{h(zh_summary)}</p>" if zh_summary and not compact and not codex_review else ""
    rule_html = (
        "<div class='source-card source-card--rules'>"
        "<div class='section-kicker'>自動規則判斷</div>"
        "<h3>關鍵字與過往資料的判斷</h3>"
        f"{badge(editorial_recommendation_label(recommendation), editorial_badge_class(recommendation))}"
        f"{badge(content_kind_label(display_kind), 'neutral')}"
        f"{badge('信心 ' + confidence, 'neutral') if confidence else ''}"
        f"{zh_summary_html}"
        f"<p class='help'>初步判斷：{h(editorial.get('summary_reason', '未標示'))}<br>"
        f"下一步：{h(editorial.get('next_step_hint', '人工判斷下一步。'))}</p>"
        f"{reason_rows}{deletion_html}{reject_reason_html}"
        "</div>"
    )
    return f"<div class='source-stack'>{codex_html}{source_html}{rule_html}</div>"


def append_review_note(review: dict, note: str) -> dict:
    updated = dict(review or default_review())
    current_notes = clean_text(updated.get("notes"))
    updated["notes"] = f"{current_notes}\n{note}".strip() if current_notes else note
    return updated


def local_decision_action(record: dict) -> str:
    decision = record.get("local_decision")
    if not isinstance(decision, dict):
        return ""
    return clean_text(decision.get("action"))


def rejected_archive_record(record: dict, decided_at: str, reason: str = "", moved_from: str = "database/items.jsonl") -> dict:
    item = remove_local_candidate_fields(record)
    item["status"] = "archived"
    item["priority"] = "low"
    decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
    previous_action = clean_text(decision.get("action"))
    item["local_decision"] = {
        **decision,
        "action": "rejected",
        "decided_at": decision.get("decided_at") if previous_action == "rejected" and decision.get("decided_at") else decided_at,
        "reason": decision.get("reason") if previous_action == "rejected" and decision.get("reason") else reason,
        "source": decision.get("source") or "local_web",
    }
    archive_meta = item.get("archive") if isinstance(item.get("archive"), dict) else {}
    item["archive"] = {
        **archive_meta,
        "moved_from": moved_from,
        "moved_to": "database/rejected-items.jsonl",
        "moved_at": decided_at,
        "purpose": "learning-rejection-patterns",
    }
    return item


def rejection_reason_base(reason: object) -> str:
    text = clean_text(reason, 140)
    return re.sub(r"（\d{4}-\d{2}-\d{2}，自動批次處理）$", "", text).strip()


def rejection_reason_suffix(reason: object) -> str:
    match = re.search(r"（\d{4}-\d{2}-\d{2}，自動批次處理）$", clean_text(reason, 160))
    return match.group(0) if match else ""


def alias_rejection_reason(reason: object) -> str:
    base = rejection_reason_base(reason)
    if base in REJECTION_REASON_CATEGORIES:
        return base
    lowered = base.casefold()
    for old_reason, category in REJECTION_REASON_ALIASES.items():
        if clean_text(old_reason).casefold() in lowered:
            return category
    return ""


def rejection_record_text(item: dict, current_reason: object = "") -> str:
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    editorial = item.get("editorial_triage") if isinstance(item.get("editorial_triage"), dict) else {}
    deletion = editorial.get("deletion_pattern_fit") if isinstance(editorial.get("deletion_pattern_fit"), dict) else {}
    decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    metadata = item_reading_metadata(item)
    review = item.get("review") if isinstance(item.get("review"), dict) else {}
    codex_review = record_codex_review(item)
    parts: list[object] = [
        current_reason,
        decision.get("reason"),
        item.get("reason"),
        item.get("notes"),
        review.get("notes"),
        item.get("title"),
        item.get("summary"),
        item.get("url"),
        item.get("source_name"),
        item.get("source_id"),
        item.get("published_at"),
        item.get("captured_at"),
        metadata.get("title"),
        metadata.get("description"),
        metadata.get("final_url"),
        metadata.get("source_url"),
        reference.get("file"),
        reference.get("stream_id"),
        editorial.get("summary_reason"),
        editorial.get("zh_summary"),
        editorial.get("content_kind_label"),
        codex_review.get("one_line_recommendation"),
        codex_review.get("summary"),
        " ".join(item.get("tags") or []),
        " ".join(triage.get("matched_keywords") or []),
        " ".join(triage.get("skip_keywords") or []),
        " ".join(str(signal) for signal in deletion.get("signals") or []),
    ]
    return " ".join(clean_text(part, 500) for part in parts if part).casefold()


def infer_rejection_reason(item: dict, current_reason: object = "") -> str:
    suffix = rejection_reason_suffix(current_reason)
    alias = alias_rejection_reason(current_reason)
    if alias:
        return f"{alias}{suffix}"

    text = rejection_record_text(item, current_reason)
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    matched_keywords = [clean_text(keyword) for keyword in triage.get("matched_keywords") or [] if clean_text(keyword)]
    skip_keywords = [clean_text(keyword) for keyword in triage.get("skip_keywords") or [] if clean_text(keyword)]

    if re.search(r"重複|已收|已涵蓋|重刊|duplicate|similar|same story", text, flags=re.I):
        return f"重複/已涵蓋{suffix}"
    published = parse_loose_date(item.get("published_at") or item.get("captured_at"))
    if published and (datetime.now(timezone.utc) - published).days >= 730:
        return f"資料太舊{suffix}"
    if re.search(r"社群內部|內部消息|會務|社群例會|籌備|organizer|maintainer update|minutes", text, flags=re.I):
        return f"社群內部消息{suffix}"
    if re.search(r"活動|報名|徵件|徵稿|招生|議程|研討會|講座|工作坊|論壇|招商|贊助|press release|webinar|conference|event|call for|cfp|sponsor", text, flags=re.I):
        return f"活動公告/宣傳{suffix}"
    if re.search(r"中國|中国|大陸|大陆|香港|澳門|澳门|央行|銀保監|证监|證監|國務院|国务院|people\.com\.cn|gov\.cn|xinhuanet|cfi\.cn|hkex|moomoo|aastocks", text, flags=re.I):
        return f"地緣脈絡非台資訊{suffix}"
    if re.search(r"股價|買超|賣超|自營商|投信|營收|財報|公告|年報|季報|法人|籌碼|個股|pdf|會議紀錄|逐字稿|transcript|minutes|record only|log", text, flags=re.I):
        return f"純紀錄型資料{suffix}"
    if len(clean_text(item.get("summary"))) < 180 and not item_article_text(item):
        return f"純紀錄型資料{suffix}"
    if skip_keywords or (candidate_recommendation(item) == "suggest-skip" and not matched_keywords):
        return f"主線關聯弱{suffix}"
    return f"主線關聯弱{suffix}"


def automatic_batch_rejection_reason(item: dict) -> str:
    base = rejection_reason_base(infer_rejection_reason(item)) or "主線關聯弱"
    today = datetime.now(LOCAL_TIMEZONE).date().isoformat()
    return f"{base}（{today}，自動批次處理）"


def latest_source_fetch_stats(source_id: str) -> dict:
    status = load_json(RSS_FETCH_STATUS)
    stats = status.get("source_stats") if isinstance(status.get("source_stats"), dict) else {}
    source_stats = stats.get(source_id) if isinstance(stats.get(source_id), dict) else {}
    return source_stats


def source_fetch_counts(stats: dict) -> dict[str, int]:
    skipped_old = int(stats.get("skipped_old") or 0)
    skipped_duplicate = int(stats.get("skipped_duplicate_recent") or 0)
    skipped_keywords = int(stats.get("skipped_source_keywords") or 0)
    return {
        "entries_seen": int(stats.get("entries_seen") or 0),
        "new_items": int(stats.get("new_items") or 0),
        "skipped_old": skipped_old,
        "skipped_duplicate_recent": skipped_duplicate,
        "skipped_source_keywords": skipped_keywords,
        "excluded_items": skipped_old + skipped_duplicate + skipped_keywords,
    }


def source_fetch_summary_from_counts(counts: dict[str, int]) -> str:
    return (
        f"重新抓 {counts.get('entries_seen', 0)} 則；"
        f"新增 {counts.get('new_items', 0)} 則；"
        f"列入排除 {counts.get('excluded_items', 0)} 則"
        f"（近 7 天重複 {counts.get('skipped_duplicate_recent', 0)}、過舊 {counts.get('skipped_old', 0)}、來源關鍵字排除 {counts.get('skipped_source_keywords', 0)}）。"
    )


def source_fetch_summary_from_query(query: dict[str, list[str]]) -> str:
    counts = {
        "entries_seen": int(form_value(query, "entries_seen", "0") or 0),
        "new_items": int(form_value(query, "new_items", "0") or 0),
        "excluded_items": int(form_value(query, "excluded_items", "0") or 0),
        "skipped_duplicate_recent": int(form_value(query, "skipped_duplicate_recent", "0") or 0),
        "skipped_old": int(form_value(query, "skipped_old", "0") or 0),
        "skipped_source_keywords": int(form_value(query, "skipped_source_keywords", "0") or 0),
    }
    return source_fetch_summary_from_counts(counts)


def rejection_reason_options(items: list[dict]) -> list[str]:
    counts: Counter[str] = Counter()
    for item in [*items, *load_jsonl(REJECTED_ITEMS), *load_jsonl(DISMISSED)]:
        decision = item.get("local_decision") or {}
        reason = ""
        if isinstance(decision, dict) and decision.get("action") == "rejected":
            reason = clean_text(decision.get("reason"), 90)
        if not reason:
            reason = clean_text(item.get("reason"), 90)
        reason = alias_rejection_reason(reason) or rejection_reason_base(reason)
        reason = re.sub(r"\s+", " ", reason).strip()
        if reason:
            counts[reason] += 1
    options = [reason for reason, _ in counts.most_common(8)]
    for reason, _ in counts.most_common(8):
        if reason and reason not in options:
            options.append(reason)
    for reason in DEFAULT_REJECTION_REASONS:
        if reason and reason not in options:
            options.append(reason)
    return options


def unique_reasons(reasons: list[str], limit: int | None = None) -> list[str]:
    output = []
    for reason in reasons:
        reason = clean_text(reason, 120)
        if reason and reason not in output:
            output.append(reason)
        if limit and len(output) >= limit:
            break
    return output


def suggested_rejection_reasons(item: dict) -> list[str]:
    triage = item.get("triage") if isinstance(item.get("triage"), dict) else {}
    text = rejection_record_text(item)
    reasons: list[str] = [rejection_reason_base(infer_rejection_reason(item))]
    skip_keywords = [clean_text(keyword) for keyword in triage.get("skip_keywords") or [] if clean_text(keyword)]
    matched_keywords = [clean_text(keyword) for keyword in triage.get("matched_keywords") or [] if clean_text(keyword)]
    recommendation = candidate_recommendation(item)

    published = parse_loose_date(item.get("published_at") or item.get("captured_at"))
    if published:
        age_days = (datetime.now(timezone.utc) - published).days
        if age_days >= 730:
            reasons.append("資料太舊")
    if re.search(r"活動|報名|徵件|徵稿|招生|研討會|講座|工作坊|webinar|conference|event|call for|cfp", text, flags=re.I):
        reasons.append("活動公告/宣傳")
    if re.search(r"抽獎|優惠|折扣|促銷|廣告|sponsored|coupon|sale|discount|職缺|招聘|hiring|job", text, flags=re.I):
        reasons.append("活動公告/宣傳")
    if re.search(r"社群內部|內部消息|會務|社群例會|籌備|organizer|maintainer update", text, flags=re.I):
        reasons.append("社群內部消息")
    if re.search(r"重複|已收|涵蓋|duplicate|similar", text, flags=re.I):
        reasons.append("重複/已涵蓋")
    if re.search(r"中國|中国|大陸|大陆|香港|澳門|澳门|銀保監|國務院|people\.com\.cn|gov\.cn|hkex|moomoo", text, flags=re.I):
        reasons.append("地緣脈絡非台資訊")
    if re.search(r"股價|買超|賣超|自營商|投信|營收|財報|公告|年報|季報|法人|籌碼|個股|會議紀錄|逐字稿|transcript|minutes", text, flags=re.I):
        reasons.append("純紀錄型資料")
    if len(clean_text(item.get("summary"))) < 180 and not item_article_text(item):
        reasons.append("純紀錄型資料")
    if not fetchable_http_url(item.get("url")):
        reasons.append("純紀錄型資料")
    if skip_keywords or (recommendation == "suggest-skip" and not matched_keywords):
        reasons.append("主線關聯弱")
    return unique_reasons(reasons, limit=5)


def prioritized_rejection_reasons(item: dict, reasons: list[str], limit: int | None = None) -> list[str]:
    return unique_reasons([*suggested_rejection_reasons(item), *reasons], limit=limit)


def review_event(item: dict, status: str, notes: str) -> dict:
    created_at = now_iso()
    return {
        "id": stable_id("review", item.get("id"), status, created_at),
        "item_id": item.get("id"),
        "track": item.get("track", "unclassified"),
        "step": "news-scout",
        "status": status,
        "reviewer": "local-web",
        "created_at": created_at,
        "notes": notes,
        "evidence": [{"type": "url", "url": item.get("url", "")}],
    }


def inline_reject_buttons(item_id: str, reasons: list[str], limit: int = 7, action: str = "/items/reject") -> str:
    buttons = []
    for reason in reasons[:limit]:
        buttons.append(
            f"""
<form class="chip-form" method="post" action="{h(action)}" data-decision-form>
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="reason" value="{h(reason)}">
  <button type="submit" class="reason-chip reason-chip--danger">{h(reason)}</button>
</form>
"""
        )
    return "\n".join(buttons)


def batch_reason_buttons(reasons: list[str], limit: int = 7) -> str:
    return "\n".join(
        f'<button type="submit" name="action" value="reject" class="reason-chip reason-chip--danger" data-batch-reason="{h(reason)}">{h(reason)}</button>'
        for reason in reasons[:limit]
    )


def candidate_issue_body(item: dict) -> str:
    triage = item.get("triage") or {}
    matched = ", ".join(triage.get("matched_keywords") or []) or "無"
    skipped = ", ".join(triage.get("skip_keywords") or []) or "無"
    return "\n".join(
        [
            "## 主線",
            track_label(item.get("track", "unclassified")),
            "",
            "## 原始網址",
            item.get("url", ""),
            "",
            "## 來源 / 網站 / 作者",
            item.get("source_name", ""),
            "",
            "## 發布日期",
            item.get("published_at", ""),
            "",
            "## 原文重點",
            clean_text(item.get("summary"), 1200),
            "",
            "## 本機關鍵字判斷",
            f"- 建議：{triage.get('recommendation', '未標示')}",
            f"- 理由：{triage.get('reason', '未標示')}",
            f"- 命中關鍵字：{matched}",
            f"- 排除關鍵字：{skipped}",
            "",
            "## 為什麼值得追",
            "本機已收下，待補切角、處理建議與審查。",
            "",
            "## 下一步",
            "- [ ] 補來源與摘要",
            "- [ ] 補切角與處理建議",
            "- [ ] 判斷是否開 PR 寫 brief 或更新 database/items.jsonl",
        ]
    )


def create_github_issue(item: dict) -> tuple[int, str]:
    title = clean_text(item.get("title"), 160) or "未命名知識候選"
    command = [
        "gh",
        "issue",
        "create",
        "--title",
        f"[知識候選] {title}",
        "--body",
        candidate_issue_body(item),
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    except FileNotFoundError:
        return 127, "找不到 gh 指令。請先安裝 GitHub CLI，或先只收進資料庫。"
    return result.returncode, result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")


def page(title: str, body: str) -> bytes:
    html_doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)} - Ian Open News</title>
  <style>
    :root {{
      --ocf-primary: #6450dc;
      --ocf-light: #d7dcf0;
      --ocf-dark: #0f1923;
      --ocf-white: #ffffff;
      --ocf-cyan: #0091da;
      --ocf-magenda: #ce0058;
      --link: #193f8f;
      --bg: #f5f6fb;
      --ink: var(--ocf-dark);
      --muted: #5f6877;
      --line: #c9d0e5;
      --panel: var(--ocf-white);
      --soft: #eef1fb;
      --accent: var(--ocf-primary);
      --humanities: var(--ocf-dark);
      --danger: #9f2525;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
      line-height: 1.55;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 16px;
      padding: 16px 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.94);
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    nav a, .nav-menu summary {{
      color: var(--ocf-dark);
      text-decoration: none;
      font-weight: 750;
      padding: 7px 10px;
      border-radius: 6px;
      transition: background .16s ease, color .16s ease, transform .16s ease;
    }}
    nav a:hover, .nav-menu summary:hover {{ background: var(--soft); color: var(--ocf-dark); transform: translateY(-1px); }}
    .nav-menu {{ position: relative; }}
    .nav-menu summary {{ list-style: none; cursor: pointer; }}
    .nav-menu summary::-webkit-details-marker {{ display: none; }}
    .nav-menu summary::after {{ content: " v"; font-size: 11px; color: var(--muted); }}
    .nav-menu[open] summary {{ background: var(--soft); color: var(--ocf-dark); }}
    .nav-menu-links {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      min-width: 210px;
      display: grid;
      gap: 4px;
      padding: 8px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 12px 30px rgba(15,25,35,.16);
      z-index: 20;
    }}
    .nav-menu-links a {{ display: flex; align-items: center; gap: 8px; }}
    h1 {{ font-size: 28px; margin: 0 0 12px; }}
    h2 {{ font-size: 20px; margin: 30px 0 12px; }}
    h3 {{ font-size: 16px; margin: 0 0 8px; }}
    .title-editor {{
      margin: 0 0 10px;
      padding: 0;
      border: 0;
      background: transparent;
    }}
    .title-editor summary {{
      cursor: pointer;
      list-style: none;
      display: grid;
      gap: 2px;
    }}
    .title-editor summary::-webkit-details-marker {{ display: none; }}
    .title-editor summary h1 {{ margin-bottom: 2px; color: var(--ocf-dark); }}
    .title-editor summary:hover h1 {{ color: var(--ocf-dark); }}
    .title-editor form {{
      max-width: 760px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    p {{ margin: 8px 0; }}
    a {{ color: var(--link); text-decoration-thickness: 1px; text-underline-offset: 2px; }}
    a:not(.button):hover {{ color: var(--ocf-primary); }}
    .masthead nav a:hover {{ color: var(--ocf-dark); }}
    a, code, .url-cell, .url, .break-anywhere {{ overflow-wrap: anywhere; word-break: break-word; }}
    .brand {{ font-weight: 850; color: var(--ocf-primary); text-decoration: none; }}
    .brand:hover {{ color: var(--ocf-dark); }}
    .lede {{ max-width: 760px; color: var(--muted); margin: 0 0 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }}
    .track-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 16px; }}
    .two-column {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr); gap: 16px; align-items: start; }}
    .card, .form-panel, table, .source-group, .filter-panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(15,25,35,.05);
    }}
    .card {{ padding: 18px; }}
    .track-card {{
      --track-color: var(--ocf-primary);
      border-top: 6px solid var(--track-color);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    .track-card--opentech {{ --track-color: var(--ocf-primary); }}
    .track-card--humanities {{ --track-color: var(--humanities); }}
    .track-card--neutral {{ --track-color: var(--ocf-cyan); }}
    .metric-row {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .metric-tile {{
      min-width: 0;
      padding: 8px;
      border-radius: 6px;
      color: var(--ink);
      text-decoration: none;
      transition: background .16s ease, transform .16s ease, box-shadow .16s ease;
    }}
    a.metric-tile:hover {{
      color: var(--ink);
      background: rgba(255,255,255,.68);
      transform: translateY(-1px);
      box-shadow: 0 5px 12px rgba(15,25,35,.10);
    }}
    .metric {{
      font-size: 27px;
      font-weight: 850;
      color: var(--track-color, var(--accent));
      line-height: 1.1;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .metric-card {{
      display: block;
      color: var(--ink);
      text-decoration: none;
      transition: transform .16s ease, box-shadow .16s ease, border-color .16s ease;
    }}
    a.metric-card:hover {{
      color: var(--ink);
      transform: translateY(-1px);
      border-color: var(--link);
      box-shadow: 0 8px 18px rgba(15,25,35,.12);
    }}
    a.metric-card:hover .metric-label {{ color: var(--muted); }}
    .metric-link-label {{
      display: inline-flex;
      margin-top: 8px;
      color: var(--link);
      font-size: 13px;
      font-weight: 800;
    }}
    a.metric-card:hover .metric-link-label, a.metric-tile:hover .metric-link-label {{ color: var(--link); text-decoration: underline; }}
    .metric-card.is-active {{
      border-color: var(--link);
      box-shadow: 0 0 0 2px rgba(25,63,143,.08);
    }}
    .muted {{ color: var(--muted); }}
    .help {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
    form {{ margin: 0; }}
    .form-panel, .filter-panel {{ padding: 18px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .date-range-fields {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .date-range-fields[hidden] {{ display: none; }}
    label {{ display: block; font-weight: 750; margin: 13px 0 5px; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }}
    textarea {{ min-height: 120px; resize: vertical; }}
    button, .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 800;
      text-decoration: none;
      cursor: pointer;
      margin-top: 12px;
      max-width: 100%;
      white-space: normal;
      text-align: center;
      transition: transform .16s ease, box-shadow .16s ease, filter .16s ease, background .16s ease;
    }}
    button:hover, .button:hover {{
      color: #fff;
      transform: translateY(-1px);
      box-shadow: 0 6px 14px rgba(15,25,35,.16);
      filter: brightness(1.03);
    }}
    button svg, .button svg {{
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
      flex: 0 0 auto;
    }}
    button:active, .button:active {{ transform: translateY(0); box-shadow: 0 2px 6px rgba(15,25,35,.14); }}
    .button-row {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; }}
    .button-row .button, .button-row button {{ margin-top: 0; }}
    .button-opentech {{ background: var(--ocf-primary); }}
    .button-humanities {{ background: var(--humanities); }}
    .secondary {{ background: var(--ocf-cyan); }}
    .quiet {{ background: var(--ocf-dark); }}
    .icon {{
      display: inline-grid;
      place-items: center;
      width: 22px;
      height: 20px;
      border-radius: 5px;
      background: rgba(255,255,255,.24);
      color: currentColor;
      font-size: 11px;
      font-weight: 900;
      line-height: 1;
      flex: 0 0 auto;
    }}
    .icon svg {{
      width: 16px;
      height: 16px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .shortcut-hint {{ display: none; white-space: nowrap; }}
    body.show-shortcuts .icon[data-shortcut] {{
      width: auto;
      min-width: 30px;
      padding: 0 4px;
      font-size: 11px;
      letter-spacing: 0;
    }}
    body.show-shortcuts .icon[data-shortcut] svg {{ display: none; }}
    body.show-shortcuts .icon[data-shortcut] .shortcut-hint {{ display: inline; }}
    .card > strong .icon, nav .icon {{
      background: var(--soft);
      color: var(--ocf-primary);
      margin-right: 6px;
    }}
    input[type="checkbox"] {{ width: auto; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; table-layout: fixed; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ background: var(--soft); color: var(--muted); font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eef1fb; padding: 2px 5px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; background: #162024; color: #eaf1ec; padding: 16px; border-radius: 8px; overflow: auto; }}
    .notice {{ border-left: 4px solid var(--ocf-primary); padding: 10px 14px; background: #eef1fb; border-radius: 6px; margin-bottom: 18px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.2;
      background: var(--soft);
      color: var(--ocf-dark);
      margin: 0 4px 4px 0;
    }}
    .badge--opentech {{ background: #ece8ff; color: var(--ocf-primary); }}
    .badge--humanities {{ background: #e6ebf5; color: var(--ocf-dark); }}
    .badge--neutral {{ background: #e7f5fc; color: #00699f; }}
    .badge--active, .badge--rss, .badge--google-alert, .badge--youtube, .badge--podcast {{ background: #e7f5fc; color: #00699f; }}
    .badge--paused {{ background: #fff0f6; color: var(--ocf-magenda); }}
    .badge--archived {{ background: #eceff5; color: #667085; }}
    .badge--suggest-keep {{ background: #ece8ff; color: var(--ocf-primary); }}
    .badge--suggest-skip {{ background: #fff0f6; color: var(--ocf-magenda); }}
    .source-group {{ margin-bottom: 14px; overflow: hidden; }}
    .source-group summary {{
      cursor: pointer;
      padding: 13px 14px;
      font-weight: 850;
      background: var(--soft);
      border-bottom: 1px solid var(--line);
    }}
    .source-group table {{ border: 0; border-radius: 0; box-shadow: none; }}
    .list {{ display: grid; gap: 10px; }}
    .list-item {{ border-left: 4px solid var(--ocf-cyan); padding: 10px 12px; background: #fff; border-radius: 6px; }}
    .list-item--opentech {{ border-left-color: var(--ocf-primary); }}
    .list-item--humanities {{ border-left-color: var(--humanities); }}
    .candidate-card {{ display: grid; gap: 10px; }}
    .candidate-card--suggest-skip {{ border-color: #f1bfd3; }}
    .candidate-card.is-removing {{
      pointer-events: none;
      overflow: hidden;
      animation: item-remove 180ms ease forwards;
    }}
    @keyframes item-remove {{
      from {{ opacity: 1; transform: translateY(0); max-height: 900px; }}
      to {{ opacity: 0; transform: translateY(-4px); max-height: 0; padding-top: 0; padding-bottom: 0; margin: 0; border-width: 0; }}
    }}
    .decision-panel {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .reason-presets {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }}
    .reason-presets button {{ margin-top: 0; }}
    .batch-panel {{ border-left: 4px solid var(--ocf-cyan); }}
    .auto-batch-panel {{
      border-left: 4px solid var(--ocf-primary);
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      margin: 14px 0;
    }}
    .auto-batch-panel button {{ margin-top: 0; }}
    .auto-batch-panel .help {{ margin: 0; flex: 1 1 280px; }}
    .keyword-filters {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .keyword-option {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ocf-dark);
      font-size: 12px;
      font-weight: 750;
    }}
    .select-item {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
      margin: 0 0 4px;
    }}
    .chip-form {{ display: inline-flex; margin: 0; }}
    .reason-chip {{
      margin-top: 0;
      padding: 6px 8px;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ocf-dark);
      font-size: 12px;
      font-weight: 800;
    }}
    .reason-chip:hover {{
      background: #fff;
      color: var(--ocf-dark);
      box-shadow: 0 4px 10px rgba(15,25,35,.12);
      transform: none;
      filter: none;
    }}
    .reason-chip--danger {{
      border-color: #f1bfd3;
      background: #fff0f6;
      color: var(--ocf-magenda);
    }}
    .reason-chip--danger:hover {{
      border-color: #f1bfd3;
      background: #fff0f6;
      color: var(--ocf-magenda);
    }}
    .inline-select-form {{ display: inline-flex; margin: 0; }}
    .inline-select-form select {{
      width: auto;
      min-width: 112px;
      margin: 0;
      padding: 6px 28px 6px 8px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.2;
      background-color: #fff;
    }}
    .source-action-row {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .source-action-row .button, .source-action-row button {{ margin-top: 0; padding: 6px 8px; font-size: 12px; }}
    .inline-reason summary {{
      cursor: pointer;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }}
    .inline-reason .button-row {{ margin-top: 8px; }}
    .danger {{ background: var(--ocf-magenda); }}
    .command-card form {{ margin-top: 8px; }}
    .command-output {{ margin-top: 16px; }}
    .preview-panel {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      border-radius: 8px;
      padding: 10px 12px;
      margin: 10px 0;
    }}
    .preview-status {{ color: var(--muted); font-size: 13px; font-weight: 750; }}
    .preview-result {{ display: grid; gap: 8px; margin-top: 8px; }}
    .preview-result h3 {{ font-size: 16px; margin: 0; }}
    .feed-suggestions {{ display: grid; gap: 8px; margin-top: 6px; }}
    .feed-suggestion {{
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 6px;
      padding: 9px 10px;
    }}
    .feed-suggestion .button {{ margin-top: 6px; padding: 7px 10px; font-size: 13px; }}
    .ai-box, .source-card {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--ocf-primary);
      background: #fbfcff;
      border-radius: 8px;
      padding: 10px 12px;
    }}
    .source-stack {{ display: grid; gap: 10px; }}
    .source-card--model {{ border-left-color: var(--ocf-primary); background: #fbfaff; }}
    .source-card--source {{ border-left-color: var(--ocf-cyan); background: #f7fbfe; }}
    .source-card--rules {{ border-left-color: #7b8495; background: #fbfcff; }}
    .source-card--empty {{ opacity: .82; }}
    .section-kicker {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: 0;
      text-transform: none;
      margin-bottom: 2px;
    }}
    .recommendation-line {{
      font-weight: 800;
      color: var(--ocf-dark);
      margin: 10px 0;
    }}
    .source-excerpt {{
      white-space: pre-wrap;
      color: var(--ink);
      margin: 10px 0 0;
    }}
    .zh-summary {{
      white-space: pre-wrap;
      margin: 8px 0;
      color: var(--ink);
      font-weight: 650;
    }}
    .reason-list {{ margin: 8px 0 0 20px; padding: 0; color: var(--ink); }}
    .reason-list li {{ margin: 4px 0; }}
    .layout-bar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin: 8px 0 12px; }}
    .layout-toggle {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
    }}
    .layout-toggle-button {{
      margin: 0;
      padding: 7px 9px;
      background: transparent;
      color: var(--ocf-dark);
      border-radius: 6px;
      box-shadow: none;
      gap: 6px;
      font-size: 13px;
    }}
    .layout-toggle-button:hover {{ background: var(--soft); color: var(--ocf-dark); box-shadow: none; transform: none; }}
    .layout-toggle-button.is-active:hover {{ color: var(--link); }}
    .layout-toggle-button.is-active {{ background: #eef1fb; color: var(--link); }}
    .layout-toggle-button svg {{
      width: 20px;
      height: 20px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .reader-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
    .reader-list {{ display: grid; gap: 10px; }}
    .reader-list-card {{
      border: 1px solid var(--line);
      border-left: 4px solid var(--link);
      border-radius: 8px;
      background: #fff;
      padding: 16px 18px;
      box-shadow: 0 1px 2px rgba(15,25,35,.04);
    }}
    .reader-list-card h3 {{
      margin: 8px 0 10px;
      font-size: 19px;
      line-height: 1.34;
    }}
    .reader-list-card h3 a {{ color: #4f3ed2; font-weight: 850; }}
    .reader-list-card .zh-summary {{
      margin: 0;
      font-size: 16px;
      line-height: 1.68;
      font-weight: 550;
    }}
    .reader-list-meta {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .reader-inbox-row {{
      display: grid;
      grid-template-columns: 11px minmax(140px, 220px) minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      padding: 11px 14px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }}
    .reader-inbox-row:last-child {{ border-bottom: 0; }}
    .reader-inbox-row:hover {{ background: #fafbff; }}
    .reader-dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--link); }}
    .reader-row-source {{ min-width: 0; color: var(--muted); font-weight: 750; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .reader-row-main {{ min-width: 0; display: flex; gap: 8px; align-items: baseline; }}
    .reader-row-main h3 {{ flex: 0 1 auto; min-width: 28%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }}
    .reader-row-summary {{ flex: 1 1 auto; min-width: 0; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .reader-row-time {{ color: var(--muted); white-space: nowrap; font-weight: 750; }}
    .reader-row-tools {{ display: inline-flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: flex-end; }}
    .reader-compact-list {{ display: grid; gap: 0; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fff; }}
    .reader-compact-row {{
      display: grid;
      grid-template-columns: 11px minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 9px 12px;
      border-bottom: 1px solid var(--line);
    }}
    .reader-compact-row:last-child {{ border-bottom: 0; }}
    .reader-compact-row h3 {{ margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; }}
    .reader-layout-section[data-layout="card"] .reader-list,
    .reader-layout-section[data-layout="card"] .reader-compact-list {{ display: none; }}
    .reader-layout-section[data-layout="list"] .reader-grid,
    .reader-layout-section[data-layout="list"] .reader-compact-list {{ display: none; }}
    .reader-layout-section[data-layout="compact"] .reader-grid,
    .reader-layout-section[data-layout="compact"] .reader-list {{ display: none; }}
    .reader-card {{
      display: grid;
      grid-template-rows: 160px auto;
      overflow: hidden;
      padding: 0;
    }}
    .reader-thumb {{
      min-height: 160px;
      background: linear-gradient(135deg, var(--ocf-primary), var(--ocf-cyan));
      color: #fff;
      display: flex;
      align-items: flex-end;
      padding: 14px;
      font-weight: 850;
    }}
    .reader-thumb--humanities {{ background: linear-gradient(135deg, var(--humanities), #2f6fb0); }}
    .reader-thumb--neutral {{ background: linear-gradient(135deg, #566172, var(--ocf-cyan)); }}
    .reader-thumb img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .reader-body {{ padding: 16px; display: grid; gap: 8px; }}
    .reader-card h3 {{ line-height: 1.35; }}
    .reader-card-actions {{
      gap: 5px;
      margin-top: 0;
      justify-content: flex-end;
      align-items: center;
    }}
    .reader-card-actions .reader-action-button {{
      width: 30px;
      height: 30px;
      min-width: 30px;
      padding: 0;
      border-radius: 6px;
      gap: 0;
      font-size: 0;
      line-height: 1;
    }}
    .reader-card-actions form {{ display: inline-flex; }}
    .reader-card-actions svg {{
      width: 15px;
      height: 15px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .reader-action-label {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
      border: 0;
    }}
    .item-hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
      gap: 18px;
      align-items: start;
    }}
    .item-image {{
      min-height: 220px;
      border-radius: 8px;
      overflow: hidden;
      background: linear-gradient(135deg, var(--ocf-primary), var(--ocf-cyan));
      color: #fff;
      display: flex;
      align-items: flex-end;
      padding: 16px;
      font-weight: 850;
    }}
    .item-image img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .note-box {{
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      padding: 10px 12px;
      border-radius: 8px;
    }}
    .fulltext-panel[hidden] {{ display: none; }}
    .article-text {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: clamp(18px, 4vw, 34px);
      background: #fff;
      max-width: 820px;
      margin: 0 auto;
      color: #17212f;
      font-size: 16px;
      line-height: 1.78;
    }}
    .reader-card .fulltext-panel .article-text {{
      max-height: 54vh;
      overflow: auto;
      padding: 16px;
      font-size: 15px;
    }}
    .article-markdown h1,
    .article-markdown h2,
    .article-markdown h3 {{
      color: var(--ocf-dark);
      line-height: 1.35;
      margin: 1.25em 0 .55em;
      letter-spacing: 0;
    }}
    .article-markdown h1 {{ font-size: 28px; margin-top: 0; }}
    .article-markdown h2 {{
      font-size: 21px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 6px;
    }}
    .article-markdown h3 {{ font-size: 18px; }}
    .article-markdown p {{ margin: 0 0 1em; }}
    .article-markdown ul,
    .article-markdown ol {{ margin: 0 0 1em 1.4em; padding: 0; }}
    .article-markdown li {{ margin: .35em 0; }}
    .article-markdown blockquote {{
      margin: 1.1em 0;
      padding: .75em 1em;
      border-left: 4px solid var(--ocf-cyan);
      background: #f7fbfe;
      color: #30445f;
    }}
    .article-markdown a {{ overflow-wrap: anywhere; }}
    .article-markdown code {{
      background: #f2f5f8;
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 1px 4px;
      font-size: .92em;
    }}
    .loading-overlay {{
      position: fixed;
      inset: 0;
      display: none;
      place-items: center;
      background: rgba(15, 25, 35, .28);
      z-index: 100;
      padding: 20px;
    }}
    .loading-overlay.is-visible {{ display: grid; }}
    .loading-card {{
      width: min(420px, 100%);
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 14px 40px rgba(15,25,35,.22);
      padding: 18px;
    }}
    .loading-dots span {{
      display: inline-block;
      width: 6px;
      height: 6px;
      margin-right: 4px;
      border-radius: 50%;
      background: var(--ocf-primary);
      animation: loading-dot 900ms infinite ease-in-out;
    }}
    .loading-dots span:nth-child(2) {{ animation-delay: 120ms; }}
    .loading-dots span:nth-child(3) {{ animation-delay: 240ms; }}
    @keyframes loading-dot {{
      0%, 80%, 100% {{ transform: translateY(0); opacity: .45; }}
      40% {{ transform: translateY(-5px); opacity: 1; }}
    }}
    .command-window {{
      position: fixed;
      right: 22px;
      bottom: 22px;
      z-index: 120;
      width: min(680px, calc(100vw - 28px));
      max-height: min(76vh, 680px);
      display: none;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 18px 48px rgba(15,25,35,.24);
      overflow: hidden;
    }}
    .command-window.is-visible {{ display: grid; grid-template-rows: auto minmax(0, 1fr); }}
    .command-window header {{
      position: static;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--soft);
    }}
    .command-window-body {{ padding: 14px; overflow: auto; }}
    .command-window pre {{ max-height: 44vh; }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; padding: 14px 18px; }}
      main {{ padding: 20px 16px; }}
      .nav-menu-links {{ left: 0; right: auto; }}
      .two-column {{ grid-template-columns: 1fr; }}
      .item-hero {{ grid-template-columns: 1fr; }}
      .metric-row {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .layout-toggle {{ width: 100%; justify-content: space-between; }}
      .layout-toggle-button {{ flex: 1 1 0; }}
      .reader-inbox-row {{ grid-template-columns: 9px minmax(0, 1fr) auto; gap: 9px; }}
      .reader-row-source {{ display: none; }}
      .reader-row-main {{ display: block; }}
      .reader-row-main h3, .reader-row-summary {{ display: block; min-width: 0; }}
      th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <a class="brand" href="/">Ian Open News</a>
    <nav>
      <details class="nav-menu">
        <summary>{icon_span("home", "H")}共通入口</summary>
        <div class="nav-menu-links">
          <a href="/">{icon_span("home", "H")}總覽</a>
          <a href="/track/open-tech-open-industry">{icon_span("globe", "O")}開放科技</a>
          <a href="/track/digital-humanities-local-knowledge">{icon_span("archive", "L")}人文知識</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("workspace", "W")}工作區</summary>
        <div class="nav-menu-links">
          <a href="/items">{icon_span("rss", "R")}RSS 待整理</a>
          <a href="/candidates">{icon_span("inbox", "C")}候選清單</a>
          <a href="/reader">{icon_span("read", "B")}閱讀區</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("plus", "N")}新增</summary>
        <div class="nav-menu-links">
          <a href="/items/new">{icon_span("plus", "N")}加收藏</a>
          <a href="/sources/new">{icon_span("rss", "R")}加 RSS</a>
        </div>
      </details>
      <details class="nav-menu">
        <summary>{icon_span("settings", "M")}管理</summary>
        <div class="nav-menu-links">
          <a href="/keywords">{icon_span("filter", "F")}關鍵字</a>
          <a href="/sources">{icon_span("source", "S")}RSS 來源</a>
        </div>
      </details>
    </nav>
  </header>
  <main>{body}</main>
  <section class="command-window" id="command-window" aria-live="polite" aria-hidden="true">
    <header>
      <strong id="command-title">本機指令</strong>
      <button type="button" class="quiet" id="command-close">關閉</button>
    </header>
    <div class="command-window-body">
      <p class="muted" id="command-status">等待執行。</p>
      <div class="loading-dots" id="command-loading" hidden><span></span><span></span><span></span></div>
      <pre id="command-output" hidden></pre>
    </div>
  </section>
  <div class="loading-overlay" id="read-more-loading" aria-live="polite" aria-hidden="true">
    <div class="loading-card">
      <strong>正在展開全文</strong>
      <p class="muted">會從原始連結往下抓全文，完成後寫成 Markdown 閱讀版存進資料庫，並在畫面展開排版後主文。</p>
      <div class="loading-dots" aria-label="載入中"><span></span><span></span><span></span></div>
    </div>
  </div>
  <div class="loading-overlay" id="codex-review-loading" aria-live="polite" aria-hidden="true">
    <div class="loading-card">
      <strong>正在生成 Codex 閱讀建議</strong>
      <p class="muted">會先嘗試補抓全文，再把單篇資料送給 Codex 產生中文標題、閱讀理由與摘要。完成後會回到這篇文章。</p>
      <div class="loading-dots" aria-label="載入中"><span></span><span></span><span></span></div>
    </div>
  </div>
  <script>
  const setShortcutMode = (active) => {{
    document.body.classList.toggle("show-shortcuts", Boolean(active));
  }};
  window.addEventListener("keydown", (event) => {{
    if (event.altKey) setShortcutMode(true);
  }});
  window.addEventListener("keyup", (event) => {{
    if (!event.altKey) setShortcutMode(false);
  }});
  window.addEventListener("blur", () => setShortcutMode(false));

  document.querySelectorAll(".nav-menu").forEach((menu) => {{
    menu.addEventListener("toggle", () => {{
      if (!menu.open) return;
      document.querySelectorAll(".nav-menu").forEach((other) => {{
        if (other !== menu) other.open = false;
      }});
    }});
  }});

  document.querySelectorAll(".layout-toggle-button").forEach((button) => {{
    button.addEventListener("click", () => {{
      const target = document.getElementById(button.dataset.layoutTarget);
      if (!target) return;
      target.dataset.layout = button.dataset.layoutMode;
      document.querySelectorAll(`.layout-toggle-button[data-layout-target="${{button.dataset.layoutTarget}}"]`).forEach((peer) => {{
        const active = peer === button;
        peer.classList.toggle("is-active", active);
        peer.setAttribute("aria-pressed", active ? "true" : "false");
      }});
    }});
  }});

  const commandWindow = document.getElementById("command-window");
  const commandTitle = document.getElementById("command-title");
  const commandStatus = document.getElementById("command-status");
  const commandOutput = document.getElementById("command-output");
  const commandLoading = document.getElementById("command-loading");
  document.getElementById("command-close")?.addEventListener("click", () => {{
    commandWindow?.classList.remove("is-visible");
    commandWindow?.setAttribute("aria-hidden", "true");
  }});

  const openCommandWindow = (label, status = "已送出，正在執行固定指令...") => {{
    commandTitle.textContent = label || "本機指令";
    commandStatus.textContent = status;
    commandOutput.hidden = true;
    commandOutput.textContent = "";
    commandLoading.hidden = false;
    commandWindow.classList.add("is-visible");
    commandWindow.setAttribute("aria-hidden", "false");
  }};

  const startElapsedStatus = () => {{
    const startedAt = Date.now();
    return window.setInterval(() => {{
      const seconds = Math.max(1, Math.round((Date.now() - startedAt) / 1000));
      commandStatus.textContent = `執行中，已等待 ${{seconds}} 秒。`;
    }}, 1000);
  }};

  const rssStatusLine = (payload) => {{
    const message = payload?.message || "正在抓取 RSS。";
    const index = payload?.source_index && payload?.selected_sources ? `（${{payload.source_index}}/${{payload.selected_sources}}）` : "";
    const total = payload?.new_items !== undefined ? `新增 ${{payload.new_items}} 則` : "";
    const excluded = payload?.excluded_items !== undefined ? `，排除 ${{payload.excluded_items}} 則` : "";
    const suffix = total ? `；${{total}}${{excluded}}` : "";
    return `${{message}}${{index}}${{suffix}}`;
  }};

  const startRssStatusPolling = () => {{
    const poll = async () => {{
      try {{
        const response = await fetch("/api/rss-status", {{headers: {{"X-Requested-With": "local-web-fetch"}}}});
        if (!response.ok) return;
        const payload = await response.json();
        commandStatus.textContent = rssStatusLine(payload);
      }} catch (_error) {{
        // Keep the command window alive; the command response will still show the final output.
      }}
    }};
    poll();
    return window.setInterval(poll, 1200);
  }};

  document.querySelectorAll("form[data-command-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const button = event.submitter || form.querySelector("button");
      const label = form.closest(".command-card")?.querySelector("strong")?.textContent?.trim()
        || form.closest(".card")?.querySelector("h3")?.textContent?.trim()
        || "本機指令";
      openCommandWindow(label);
      if (button) button.disabled = true;
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      const timer = data.get("command") === "fetch_rss" ? startRssStatusPolling() : startElapsedStatus();
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        commandStatus.textContent = payload.summary || `完成，exit code ${{payload.returncode}}。`;
        commandOutput.hidden = false;
        commandOutput.textContent = payload.output || "(沒有輸出)";
      }} catch (error) {{
        commandStatus.textContent = "指令沒有順利回傳，請看終端機或稍後再試。";
        commandOutput.hidden = false;
        commandOutput.textContent = String(error);
      }} finally {{
        if (timer) window.clearInterval(timer);
        commandLoading.hidden = true;
        if (button) button.disabled = false;
      }}
    }});
  }});

  document.querySelectorAll("form[data-source-fetch-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const button = event.submitter || form.querySelector("button");
      const sourceName = form.closest("tr")?.querySelector("strong")?.textContent?.trim()
        || document.querySelector("h1")?.textContent?.trim()
        || "RSS";
      openCommandWindow(`手動更新 RSS：${{sourceName}}`, "已送出，正在抓取這個 RSS...");
      if (button) button.disabled = true;
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      const timer = startRssStatusPolling();
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        commandStatus.textContent = payload.summary || `完成，exit code ${{payload.returncode}}。`;
        commandOutput.hidden = false;
        commandOutput.textContent = payload.output || payload.summary || "(沒有輸出)";
      }} catch (error) {{
        commandStatus.textContent = "手動更新 RSS 沒有順利回傳，請看終端機或稍後再試。";
        commandOutput.hidden = false;
        commandOutput.textContent = String(error);
      }} finally {{
        if (timer) window.clearInterval(timer);
        commandLoading.hidden = true;
        if (button) button.disabled = false;
      }}
    }});
  }});

  const escapeHTML = (value) => String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const setIfEmpty = (element, value) => {{
    if (!element || !value || element.value.trim()) return;
    element.value = value;
  }};

  const previewInputValue = (form) => {{
    const kind = form.getAttribute("data-preview-kind") || "item";
    if (kind === "source") {{
      const feed = form.querySelector("[data-preview-feed-url]")?.value?.trim();
      const site = form.querySelector("[data-preview-site-url]")?.value?.trim();
      return feed || site || "";
    }}
    return form.querySelector("[data-preview-url]")?.value?.trim() || "";
  }};

  const feedSuggestionHTML = (feeds) => {{
    if (!feeds?.length) return "<p class='help'>沒有在這頁偵測到 RSS / Atom feed。</p>";
    return `<div class="feed-suggestions">${{feeds.map((feed) => {{
      const status = feed.exists ? "<span class='badge badge--neutral'>已追蹤</span>" : "<span class='badge badge--rss'>可新增 RSS</span>";
      const action = feed.exists
        ? ""
        : `<a class="button secondary" href="${{escapeHTML(feed.add_url)}}">新增這個 RSS</a>`;
      return `<div class="feed-suggestion">
        <strong>${{escapeHTML(feed.title || feed.url)}}</strong> ${{status}}
        <p class="help break-anywhere">${{escapeHTML(feed.type || "RSS / Atom")}} · ${{escapeHTML(feed.url)}}</p>
        ${{action}}
      </div>`;
    }}).join("")}}</div>`;
  }};

  const renderPreview = (form, payload) => {{
    const kind = form.getAttribute("data-preview-kind") || "item";
    const result = form.querySelector("[data-preview-result]");
    const status = form.querySelector("[data-preview-status]");
    const title = payload.feed_title || payload.title || payload.source_name || payload.final_url || payload.url;
    const description = payload.description || payload.excerpt || "";
    if (status) {{
      const parts = [];
      if (payload.is_feed) parts.push(`${{payload.feed_type || "RSS"}}，${{payload.entry_count || 0}} 則`);
      if (payload.final_url && payload.final_url !== payload.url) parts.push("已帶入跳轉後網址");
      status.textContent = parts.length ? `抓到了：${{parts.join("；")}}。` : "已抓到頁面資訊。";
    }}
    if (result) {{
      result.innerHTML = `
        <div>
          <h3>${{escapeHTML(title)}}</h3>
          <p class="help break-anywhere">${{escapeHTML(payload.final_url || payload.url || "")}}</p>
          ${{description ? `<p>${{escapeHTML(description)}}</p>` : ""}}
        </div>
        <div>
          <strong>RSS 建議</strong>
          ${{feedSuggestionHTML(payload.feed_suggestions || [])}}
        </div>
      `;
    }}

    if (kind === "item") {{
      const urlInput = form.querySelector("[data-preview-url]");
      if (urlInput && payload.unwrapped_url) urlInput.value = payload.unwrapped_url;
      setIfEmpty(form.querySelector("[data-preview-title]"), payload.title || payload.feed_title);
      setIfEmpty(form.querySelector("[data-preview-source-name]"), payload.source_name);
      setIfEmpty(form.querySelector("[data-preview-summary]"), description);
    }} else {{
      const feedInput = form.querySelector("[data-preview-feed-url]");
      const siteInput = form.querySelector("[data-preview-site-url]");
      const nameInput = form.querySelector("[data-preview-title]");
      const typeInput = form.querySelector("[data-preview-source-type]");
      const firstFeed = (payload.feed_suggestions || [])[0];
      setIfEmpty(nameInput, payload.feed_title || payload.title || payload.source_name);
      setIfEmpty(siteInput, payload.site_url || (!payload.is_feed ? payload.final_url : ""));
      if (payload.is_feed) {{
        setIfEmpty(feedInput, payload.final_url || payload.url);
      }} else if (firstFeed && (!feedInput?.value?.trim() || feedInput.value.trim() === payload.url)) {{
        feedInput.value = firstFeed.url;
      }}
      if (typeInput && !typeInput.value) typeInput.value = "rss";
    }}
  }};

  const runUrlPreview = async (form, force = false) => {{
    const url = previewInputValue(form);
    const panel = form.querySelector("[data-preview-panel]");
    const status = form.querySelector("[data-preview-status]");
    const button = form.querySelector("[data-preview-button]");
    if (!url || !url.startsWith("http")) return;
    if (!force && form.dataset.previewLast === url) return;
    form.dataset.previewLast = url;
    if (panel) panel.hidden = false;
    if (status) status.textContent = "正在抓取頁面與 RSS 資訊...";
    if (button) button.disabled = true;
    const data = new URLSearchParams();
    data.set("url", url);
    data.set("track", form.querySelector("[data-preview-track]")?.value || "digital-humanities-local-knowledge");
    try {{
      const response = await fetch("/preview-url", {{
        method: "POST",
        headers: {{
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Requested-With": "local-web-fetch"
        }},
        body: data
      }});
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "preview failed");
      renderPreview(form, payload);
    }} catch (error) {{
      if (status) status.textContent = `這次沒有抓到頁面資訊：${{String(error)}}`;
    }} finally {{
      if (button) button.disabled = false;
    }}
  }};

  document.querySelectorAll("form[data-url-preview-form]").forEach((form) => {{
    let timer = 0;
    const schedule = () => {{
      window.clearTimeout(timer);
      timer = window.setTimeout(() => runUrlPreview(form), 850);
    }};
    form.querySelector("[data-preview-button]")?.addEventListener("click", () => runUrlPreview(form, true));
    form.querySelectorAll("[data-preview-url], [data-preview-site-url]").forEach((input) => {{
      input.addEventListener("change", () => runUrlPreview(form, true));
      input.addEventListener("blur", () => runUrlPreview(form, true));
      input.addEventListener("input", schedule);
    }});
    if (previewInputValue(form)) window.setTimeout(() => runUrlPreview(form), 250);
  }});

  document.querySelectorAll("form[data-read-more-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const overlay = document.getElementById("read-more-loading");
      if (overlay) {{
        overlay.classList.add("is-visible");
        overlay.setAttribute("aria-hidden", "false");
      }}
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      try {{
        const targetUrl = form.getAttribute("action") || form.action;
        const response = await fetch(targetUrl, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        if (!payload.ok) throw new Error(payload.error || "read more failed");
        const targetSelector = form.getAttribute("data-target") || "#fulltext-panel";
        const panel = document.querySelector(targetSelector);
        if (panel) {{
          panel.hidden = false;
          const body = panel.querySelector("[data-fulltext-body]");
          const meta = panel.querySelector("[data-fulltext-meta]");
          if (body) {{
            if (payload.article_html) {{
              body.innerHTML = payload.article_html;
            }} else {{
              body.textContent = payload.article_text || "這次沒有抓到可顯示的主文。";
            }}
          }}
          if (meta) meta.textContent = payload.message || "";
          const translationActions = panel.querySelector("[data-translation-actions]");
          if (translationActions) {{
            if (payload.translation_actions_html) {{
              translationActions.innerHTML = payload.translation_actions_html;
              translationActions.hidden = false;
            }} else {{
              translationActions.innerHTML = "";
              translationActions.hidden = true;
            }}
          }}
          panel.scrollIntoView({{ behavior: "smooth", block: "start" }});
        }} else if (payload.redirect) {{
          window.location.href = payload.redirect;
        }}
      }} catch (error) {{
        const redirect = form.querySelector("input[name='redirect']")?.value || window.location.pathname + window.location.search;
        const separator = redirect.includes("?") ? "&" : "?";
        window.location.href = redirect + separator + "error=read_more";
      }} finally {{
        if (overlay) {{
          overlay.classList.remove("is-visible");
          overlay.setAttribute("aria-hidden", "true");
        }}
      }}
    }});
  }});

  document.querySelectorAll("form[data-codex-review-form]").forEach((form) => {{
    form.addEventListener("submit", async (event) => {{
      if (!window.fetch) return;
      event.preventDefault();
      const overlay = document.getElementById("codex-review-loading");
      const button = event.submitter || form.querySelector("button");
      if (overlay) {{
        overlay.classList.add("is-visible");
        overlay.setAttribute("aria-hidden", "false");
      }}
      if (button) button.disabled = true;
      const data = new URLSearchParams(new FormData(form));
      data.set("format", "json");
      try {{
        const response = await fetch(form.getAttribute("action") || form.action, {{
          method: "POST",
          headers: {{
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "local-web-fetch"
          }},
          body: data
        }});
        const payload = await response.json();
        if (!payload.ok) throw new Error(payload.error || "codex review failed");
        window.location.href = payload.redirect || window.location.href;
      }} catch (error) {{
        const redirect = form.querySelector("input[name='redirect']")?.value || window.location.pathname + window.location.search;
        const separator = redirect.includes("?") ? "&" : "?";
        window.location.href = redirect + separator + "error=codex_review";
      }} finally {{
        if (overlay) {{
          overlay.classList.remove("is-visible");
          overlay.setAttribute("aria-hidden", "true");
        }}
        if (button) button.disabled = false;
      }}
    }});
  }});
  </script>
</body>
</html>"""
    return html_doc.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "IanOpenNewsLocal/1.0"

    def send_html(self, title: str, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_reader_asset(self, path: str) -> None:
        relative = path.removeprefix("/reader/assets/").lstrip("/")
        asset_root = ROOT / "docs" / "reader" / "assets"
        target = (asset_root / relative).resolve()
        try:
            target.relative_to(asset_root.resolve())
        except ValueError:
            self.send_html("找不到", "<h1>找不到檔案</h1>", HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_html("找不到", "<h1>找不到檔案</h1>", HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(content)

    def redirect(self, path: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
        self.end_headers()

    def is_async_request(self) -> bool:
        return self.headers.get("X-Requested-With") == "local-web-fetch"

    def send_no_content(self, status: HTTPStatus = HTTPStatus.NO_CONTENT) -> None:
        self.send_response(status)
        self.end_headers()

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return parse_qs(raw)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self.show_home(query)
        elif parsed.path.startswith("/reader/assets/"):
            self.send_reader_asset(parsed.path)
        elif parsed.path.startswith("/track/"):
            self.show_track(parsed.path.removeprefix("/track/"))
        elif parsed.path == "/candidates":
            self.show_candidates(query)
        elif parsed.path == "/reader":
            self.show_reader(query)
        elif parsed.path == "/rss-candidates":
            suffix = f"?{parsed.query}" if parsed.query else ""
            self.redirect(f"/items{suffix}")
        elif parsed.path == "/keywords":
            self.show_keywords()
        elif parsed.path == "/items":
            self.show_items(query)
        elif parsed.path == "/items/view":
            self.show_item_detail(query)
        elif parsed.path == "/items/reject":
            self.show_item_reject_form(query)
        elif parsed.path == "/items/new":
            self.show_item_form(query)
        elif parsed.path == "/sources":
            self.show_sources(query)
        elif parsed.path == "/sources/view":
            self.show_source_view(query)
        elif parsed.path == "/sources/new":
            self.show_source_form(
                {
                    "track": (query.get("track") or ["digital-humanities-local-knowledge"])[0],
                    "source_type": (query.get("source_type") or ["rss"])[0],
                    "source_group": clean_text(unquote((query.get("source_group") or ["Manual RSS"])[0])),
                    "name": clean_text(unquote((query.get("name") or [""])[0])),
                    "feed_url": clean_text(unquote((query.get("feed_url") or [""])[0])),
                    "site_url": clean_text(unquote((query.get("site_url") or [""])[0])),
                }
            )
        elif parsed.path == "/sources/edit":
            self.show_source_edit(query)
        elif parsed.path == "/api/rss-status":
            self.send_json(load_json(RSS_FETCH_STATUS))
        elif parsed.path == "/api/data-commit-status":
            self.send_json(load_json(DATA_COMMIT_STATUS))
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/items":
            self.save_item(self.read_form())
        elif parsed.path == "/items/accept":
            self.accept_item(self.read_form())
        elif parsed.path == "/items/direct-pr":
            self.direct_pr_item(self.read_form())
        elif parsed.path == "/items/reject":
            self.reject_item(self.read_form())
        elif parsed.path == "/items/batch":
            self.batch_items(self.read_form())
        elif parsed.path == "/items/auto-batch-skip":
            self.auto_batch_skip_items(self.read_form())
        elif parsed.path == "/items/personal-note":
            self.save_personal_note(self.read_form())
        elif parsed.path == "/items/requeue-skill":
            self.requeue_skill_item(self.read_form())
        elif parsed.path == "/items/read-more":
            self.read_more_item(self.read_form())
        elif parsed.path == "/items/codex-review":
            self.codex_review_item(self.read_form())
        elif parsed.path == "/items/update-url":
            self.update_item_url(self.read_form())
        elif parsed.path == "/items/update-title":
            self.update_item_title(self.read_form())
        elif parsed.path == "/items/update-metadata":
            self.update_item_metadata(self.read_form())
        elif parsed.path == "/items/translate-zh":
            self.translate_item_zh(self.read_form())
        elif parsed.path == "/preview-url":
            self.preview_url(self.read_form())
        elif parsed.path == "/candidates/accept":
            self.accept_candidate(self.read_form())
        elif parsed.path == "/candidates/dismiss":
            self.dismiss_candidate(self.read_form())
        elif parsed.path == "/keywords":
            self.save_keywords(self.read_form())
        elif parsed.path == "/sources":
            self.save_source(self.read_form())
        elif parsed.path == "/sources/quick-update":
            self.quick_update_source(self.read_form())
        elif parsed.path == "/sources/fetch":
            self.fetch_source_now_post(self.read_form())
        elif parsed.path == "/sources/restore-item":
            self.restore_source_item(self.read_form())
        elif parsed.path == "/commands/run":
            self.run_command(self.read_form())
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def show_home(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        candidates = load_jsonl(CANDIDATES)
        sources = load_jsonl(SOURCES)
        candidates = load_jsonl(CANDIDATES)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        skill_candidates = [item for item in items if is_skill_candidate(item)]
        direct_pr_items = [item for item in items if is_direct_pr_item(item)]
        reader_items = [item for item in items if is_reader_item(item)]
        pending_review_items = [*candidates, *inbox_items]
        pending_counts = Counter(candidate_recommendation(item) for item in pending_review_items)
        notice = ""
        if query.get("saved"):
            notice = '<div class="notice">已儲存。</div>'
        data_commit_status = load_json(DATA_COMMIT_STATUS)
        data_commit_message_text = clean_text(data_commit_status.get("message")) or "自動 commit 排程會在 local web 執行期間每 30 分鐘檢查一次。"
        data_commit_next = clean_text(data_commit_status.get("next_run_at")) or "尚未排程"
        data_commit_last = clean_text(data_commit_status.get("updated_at")) or "尚未記錄"
        host = self.headers.get("Host", "127.0.0.1:8765")
        bookmarklet = (
            f"javascript:location.href='http://{host}/items/new?url='"
            "+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)"
        )
        track_cards = []
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge"]:
            meta = track_meta(track)
            css_class = track_class(track)
            total_items = count_items(items, track)
            pending_items = sum(1 for item in pending_review_items if item.get("track") == track)
            source_count = count_sources(sources, track)
            fetchable_count = count_sources(sources, track, active_only=True)
            button_class = f"button-{css_class}" if css_class in {"opentech", "humanities"} else "secondary"
            track_cards.append(
                f"""
  <section class="card track-card track-card--{h(css_class)}">
    <div>
      {badge(meta["short"], css_class)}
      <h2>{h(meta["label"])}</h2>
      <p class="muted">{h(meta["description"])}</p>
    </div>
    <div class="metric-row">
      {metric_tile(total_items, "全部項目", f"/track/{quote(track)}", "看主線")}
      {metric_tile(pending_items, "待整理", href_with_query("/items", [("track", track)]), "篩選待整理")}
      {metric_tile(source_count, "來源", href_with_query("/sources", [("track", track)]), "看來源")}
      {metric_tile(fetchable_count, "會自動抓", href_with_query("/sources", [("track", track), ("status", "active")]), "只看啟用")}
    </div>
    <div class="button-row reader-card-actions">
      <a class="button {h(button_class)}" href="/track/{quote(track)}">{h(meta["entry"])}</a>
      <a class="button secondary" href="/sources?track={quote(track)}">看這類 RSS 來源</a>
    </div>
    <p class="help">第一顆按鈕是看這條主線的待整理資料；第二顆是檢查這條主線目前追蹤哪些網站或 feed。</p>
  </section>
"""
            )
        command_cards = [command_card(name, config) for name, config in COMMANDS.items()]
        body = f"""
<h1>共通入口</h1>
<p class="lede">這裡是每天 RSS 自動抓取、手動收藏、資料檢查與兩條知識主線的起點。資料正本仍在 GitHub 裡的 JSONL，網頁只是讓你比較好操作。</p>
{notice}
<div class="track-grid">{''.join(track_cards)}</div>
<h2>共用工具</h2>
<div class="grid">
  <div class="card">
    <h3>看到好頁面</h3>
    <p class="muted">把這顆拖到瀏覽器書籤列。之後看到想記下來的頁面，點書籤就會開出「加收藏」表單。</p>
    <p><a class="button" href="{h(bookmarklet)}">做成瀏覽器收藏按鈕</a></p>
    <p class="help">這不會直接發布內容，只是先放進待整理 inbox。</p>
  </div>
  <div class="card">
    <h3>RSS 待整理</h3>
    <p class="muted">每天 RSS 新進與已入庫 inbox 都在這裡分流。</p>
    <div class="metric-row">
      {metric_tile(len(pending_review_items), "全部", "/items", "打開")}
      {metric_tile(pending_counts.get("suggest-keep", 0), "建議收", "/items?recommendation=suggest-keep", "只看")}
      {metric_tile(pending_counts.get("suggest-skip", 0), "建議不要看", "/items?recommendation=suggest-skip", "只看")}
    </div>
    <p><a class="button" href="/items">打開 RSS 待整理</a></p>
    <p class="help">確認收會直接進候選清單，不收會移出主資料庫並保留到學習檔，純小消息可直接標記送 PR。</p>
  </div>
  <div class="card">
    <h3>候選清單</h3>
    <p class="muted">只放你已確認收下、準備跑 skill 編修的文章。</p>
    <div class="metric-row">
      {metric_tile(len(skill_candidates), "待跑 skill", "/candidates", "打開")}
      {metric_tile(len(direct_pr_items), "直接送 PR", "/reader?kind=small-news&time=all", "看小消息")}
    </div>
    <p><a class="button" href="/candidates">打開候選清單</a></p>
    <p class="help">RSS 新資料請先在 RSS 待整理處理；純小消息可在同一頁直接標記送 PR。</p>
  </div>
  <div class="card">
    <h3>閱讀區</h3>
    <p class="muted">閱讀已確認收下的精選文章與小消息，並補你的個人觀點。</p>
    <div class="metric-row">
      {metric_tile(len(reader_items), "可閱讀", "/reader?time=all", "看全部")}
    </div>
    <p><a class="button" href="/reader">打開閱讀區</a></p>
    <p class="help">在閱讀區可寫「我的關鍵紀錄」，也能把好文章重新送回 skill 依你的觀點改寫。</p>
  </div>
  <div class="card">
    <h3>新增 RSS 來源</h3>
    <p class="muted">看到值得長期追蹤的網站、Google 快訊、YouTube 或 Podcast，就先加到來源資料庫。</p>
    <p><a class="button secondary" href="/sources/new">新增一個 RSS</a></p>
    <p class="help">新增後每天 12:00、18:00、23:00 的流程才會有機會抓到它。</p>
  </div>
  <div class="card">
    <h3>調整關鍵字</h3>
    <p class="muted">兩條主線各有「建議收」與「建議不要看」關鍵字，可隨時改。</p>
    <p><a class="button quiet" href="/keywords">編輯篩選關鍵字</a></p>
    <p class="help">改完後，下一次 RSS 抓取就會套用新的判斷。</p>
  </div>
  <div class="card">
    <h3>全部 RSS 來源</h3>
    <p class="muted">依主線、來源類型、來源群組查看目前追蹤中的網站，也可以進去編輯或暫停。</p>
    <p><a class="button quiet" href="/sources">打開來源列表</a></p>
    <p class="help">長網址會自動換行，不會把表格撐爆。</p>
  </div>
  <div class="card">
    <h3>閱讀資料庫狀態</h3>
    <p class="muted">固定保護本機編輯狀態，只送出 items、review-events、sources 三個資料檔。</p>
    <form method="post" action="/commands/run" data-command-form>
      <input type="hidden" name="command" value="commit_database_state">
      <button type="submit" class="secondary">送 commit 儲存狀態</button>
    </form>
    <p class="help">最近狀態：{h(data_commit_message_text)}<br>最近更新：{h(data_commit_last)}<br>下次自動檢查：{h(data_commit_next)}</p>
  </div>
</div>
<h2>本機指令</h2>
<p class="lede">這些按鈕只會執行固定 allowlist 指令；每顆按鈕下方都有白話說明，方便你不用記終端機命令。</p>
<div class="grid">{''.join(command_cards)}</div>
"""
        self.send_html("總覽", body)

    def show_items(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        candidates = load_jsonl(CANDIDATES)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        pending_entries = [("rss", candidate) for candidate in candidates] + [("item", item) for item in inbox_items]
        track_filter = (query.get("track") or ["all"])[0]
        recommendation_filter = (query.get("recommendation") or ["all"])[0]
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}
        show_all = (query.get("show") or [""])[0] == "all"

        def matches_basic(record: dict) -> bool:
            if track_filter != "all" and record.get("track") != track_filter:
                return False
            if recommendation_filter != "all" and candidate_recommendation(record) != recommendation_filter:
                return False
            return True

        def matches(record: dict) -> bool:
            if not matches_basic(record):
                return False
            if selected_keywords and not (item_triage_keywords(record) & selected_keywords):
                return False
            return True

        keyword_source_entries = [entry for entry in pending_entries if matches_basic(entry[1])]
        keyword_counts = Counter(keyword for _, record in keyword_source_entries for keyword in item_triage_keywords(record))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)

        filtered = [entry for entry in pending_entries if matches(entry[1])]
        filtered.sort(
            key=lambda entry: (
                entry[1].get("captured_at", ""),
                entry[1].get("published_at", ""),
                entry[1].get("title", ""),
            ),
            reverse=True,
        )
        filtered.sort(key=lambda entry: candidate_recommendation(entry[1]) == "suggest-skip")
        visible = filtered if show_all else filtered[:150]
        summary_entries = [
            entry
            for entry in pending_entries
            if (track_filter == "all" or entry[1].get("track") == track_filter)
            and (not selected_keywords or bool(item_triage_keywords(entry[1]) & selected_keywords))
        ]
        counts = Counter(candidate_recommendation(record) for _, record in summary_entries)
        track_counts = Counter(record.get("track", "unclassified") for _, record in pending_entries)

        def items_metric_href(recommendation: str = "") -> str:
            params = []
            if track_filter != "all":
                params.append(("track", track_filter))
            if recommendation:
                params.append(("recommendation", recommendation))
            for keyword in sorted(selected_keywords):
                params.append(("keyword", keyword))
            return href_with_query("/items", params)

        reason_options = rejection_reason_options(items)
        notice = ""
        if (query.get("saved") or [""])[0] == "accepted":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已確認收下 {count} 筆。處理過的項目已離開 RSS 待整理，現在可到候選清單的「待跑 skill」區接著編修。</div>'
        elif (query.get("saved") or [""])[0] == "auto_rejected":
            count = h((query.get("count") or ["0"])[0])
            notice = f'<div class="notice">已用自動批次處理標記不收 {count} 筆，並依每則標題、網址與既有理由寫入新版不收分類。</div>'
        elif (query.get("saved") or [""])[0] == "rejected":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已標記不收 {count} 筆，項目已離開 RSS 待整理，原因也已寫進不收學習檔與 review event。</div>'
        elif (query.get("error") or [""])[0] == "empty-selection":
            notice = '<div class="notice">請先勾選至少一則，再做批次處理。</div>'
        elif (query.get("error") or [""])[0] == "reason":
            notice = '<div class="notice">批次不收或自訂不收時，請先填原因。</div>'
        elif (query.get("saved") or [""])[0] == "direct_pr":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已標記 {count} 筆直接送 PR 小消息。它們已離開 RSS 待整理，並留下紀錄。</div>'
        elif (query.get("saved") or [""])[0] == "queued":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已收進 RSS 待整理 {count} 筆，現在可在同一頁做最後分流。</div>'
        elif (query.get("saved") or [""])[0] == "dismissed":
            count = h((query.get("count") or ["1"])[0])
            notice = f'<div class="notice">已略過 RSS 新進 {count} 筆，之後同一筆不會重複出現。</div>'
        rows = []
        for entry_type, item in visible:
            triage = item.get("triage") or {}
            recommendation = candidate_recommendation(item)
            matched = "、".join(triage.get("matched_keywords") or []) or "無"
            skipped = "、".join(triage.get("skip_keywords") or []) or "無"
            css_class = track_class(item.get("track", "unclassified"))
            item_id = str(item.get("id") or "")
            if entry_type == "rss":
                detail_href = item_detail_href(item)
                rows.append(
                    f"""
<article class="card candidate-card candidate-card--{h(recommendation)}" data-item-id="{h(item_id)}">
  <label class="select-item">
    <input type="checkbox" class="item-select" value="{h(item_id)}">
    選取這則做批次處理
  </label>
  <div>
    {badge("RSS 新進", "neutral")}
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge(recommendation_label(recommendation), recommendation)}
    <strong><a href="{h(detail_href)}">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  <p class="help">判斷理由：{h(triage.get('reason', '未標示'))}<br>命中關鍵字：{h(matched)}<br>排除關鍵字：{h(skipped)}</p>
  <div class="decision-panel">
    <div class="button-row">
      <form method="post" action="/candidates/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="decision" value="accept">
        <button type="submit">{button_content("確認收，準備跑 skill", "accept", "A")}</button>
      </form>
      <form method="post" action="/candidates/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="decision" value="direct_pr">
        <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
      </form>
    </div>
    <p class="help">這則還在 RSS 新進。確認收或直接送 PR 時，系統會先寫進 database/items.jsonl，再套用你的決定；不收會寫入不收學習檔與略過清單。</p>
    <p class="help">不收原因</p>
    <div class="reason-presets">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options), action="/candidates/dismiss")}</div>
    <details class="inline-reason">
      <summary>其他原因</summary>
      <form method="post" action="/candidates/dismiss" data-decision-form data-require-reason>
        <input type="hidden" name="id" value="{h(item_id)}">
        <div class="button-row">
          <input name="reason" placeholder="寫一句不收原因">
          <button type="submit" class="reason-chip reason-chip--danger">{button_content("記錄不收", "reject", "X")}</button>
        </div>
      </form>
    </details>
  </div>
  {editorial_triage_html(item, compact=True)}
</article>
"""
                )
                continue
            detail_href = item_detail_href(item)
            rows.append(
                f"""
<article class="card candidate-card candidate-card--{h(recommendation)}" data-item-id="{h(item_id)}">
  <label class="select-item">
    <input type="checkbox" class="item-select" value="{h(item_id)}">
    選取這則做批次處理
  </label>
  <div>
    {badge("已入庫待分流", "neutral")}
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge(recommendation_label(recommendation), recommendation)}
    <strong><a href="{h(detail_href)}">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  <p class="help">判斷理由：{h(triage.get('reason', '未標示'))}<br>命中關鍵字：{h(matched)}<br>排除關鍵字：{h(skipped)}</p>
  <div class="decision-panel">
    <div class="button-row">
      <form method="post" action="/items/accept" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit">{button_content("確認收，準備跑 skill", "accept", "A")}</button>
      </form>
      <form method="post" action="/items/direct-pr" data-decision-form>
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
      </form>
    </div>
    <p class="help">確認收會移到候選清單待跑 skill；純事實小消息可直接記錄為送 PR，不跑 skill。</p>
    <p class="help">不收原因</p>
    <div class="reason-presets">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options))}</div>
    <details class="inline-reason">
      <summary>其他原因</summary>
      <form method="post" action="/items/reject" data-decision-form data-require-reason>
        <input type="hidden" name="id" value="{h(item_id)}">
        <div class="button-row">
          <input name="reason" placeholder="寫一句不收原因">
          <button type="submit" class="reason-chip reason-chip--danger">{button_content("記錄不收", "reject", "X")}</button>
        </div>
      </form>
    </details>
  </div>
  {editorial_triage_html(item)}
</article>
"""
            )
        if not rows:
            rows.append('<div class="card"><strong>目前沒有符合條件的 RSS 待整理項目</strong><p class="muted">換一個篩選條件，或先重新跑關鍵字判斷。</p></div>')

        more_link = ""
        if not show_all and len(filtered) > len(visible):
            parts = []
            if track_filter != "all":
                parts.append(f"track={quote(track_filter)}")
            if recommendation_filter != "all":
                parts.append(f"recommendation={quote(recommendation_filter)}")
            for keyword in sorted(selected_keywords):
                parts.append(f"keyword={quote(keyword)}")
            parts.append("show=all")
            more_link = f'<p><a class="button secondary" href="/items?{"&".join(parts)}">顯示全部 {len(filtered)} 筆</a></p>'

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        recommendation_options = [
            ("all", "全部建議"),
            ("suggest-keep", "只看建議收"),
            ("suggest-skip", "只看建議不要看"),
        ]
        keyword_filters = []
        for keyword in keyword_options:
            checked = " checked" if keyword in selected_keywords else ""
            count = keyword_counts.get(keyword, 0)
            keyword_filters.append(
                f"""
<label class="keyword-option">
  <input type="checkbox" name="keyword" value="{h(keyword)}"{checked}>
  {h(keyword)} <span class="muted">({count})</span>
</label>
"""
            )
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用關鍵字。</p>'
        batch_buttons = batch_reason_buttons(reason_options)
        auto_batch_panel = ""
        if recommendation_filter == "suggest-skip" and filtered:
            auto_hidden_inputs = [
                f'<input type="hidden" name="track" value="{h(track_filter)}">',
                '<input type="hidden" name="recommendation" value="suggest-skip">',
            ]
            if show_all:
                auto_hidden_inputs.append('<input type="hidden" name="show" value="all">')
            for keyword in sorted(selected_keywords):
                auto_hidden_inputs.append(f'<input type="hidden" name="keyword" value="{h(keyword)}">')
            auto_batch_panel = f"""
<div class="card auto-batch-panel">
  <form method="post" action="/items/auto-batch-skip">
    {''.join(auto_hidden_inputs)}
    <button type="submit" class="secondary">{button_content("自動批次處理", "wand", "W")}</button>
  </form>
  <p class="help">會處理這個 view 下的 {len(filtered)} 筆「建議不要看」，逐筆推估不收分類，並在原因後加上「{datetime.now(LOCAL_TIMEZONE).date().isoformat()}，自動批次處理」。</p>
</div>
"""
        body = f"""
<h1>RSS 待整理</h1>
<p class="lede">這裡是本機人工篩選台。RSS 新進和已入庫 inbox 會一起出現；處理過的項目會立刻離開這裡。確認收後會移到候選清單的「待跑 skill」區，整理好才進 GitHub PR。</p>
{notice}
<div class="grid">
  {metric_card(len(summary_entries), "全部待整理", items_metric_href(), "看全部", "is-active" if recommendation_filter == "all" else "")}
  {metric_card(counts.get("suggest-keep", 0), "建議收", items_metric_href("suggest-keep"), "只看建議收", "is-active" if recommendation_filter == "suggest-keep" else "")}
  {metric_card(counts.get("suggest-skip", 0), "建議不要看", items_metric_href("suggest-skip"), "只看建議不要看", "is-active" if recommendation_filter == "suggest-skip" else "")}
</div>
<h2>篩選 RSS 待整理</h2>
<form class="filter-panel" method="get" action="/items" id="items-filter-form">
  {'<input type="hidden" name="show" value="all">' if show_all else ''}
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
      <p class="help">選完會自動更新。開放科技 {track_counts.get('open-tech-open-industry', 0)}、人文 {track_counts.get('digital-humanities-local-knowledge', 0)}、未分類 {track_counts.get('unclassified', 0)}。</p>
    </div>
    <div>
      <label>系統建議</label>
      <select name="recommendation" class="auto-filter">{option_list(recommendation_options, recommendation_filter)}</select>
      <p class="help">已跑 Codex 的項目優先看 Codex 判斷；還沒跑前維持第一段關鍵字初篩。改完關鍵字後可到關鍵字頁重新跑。</p>
    </div>
  </div>
  <label>關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/items">清除篩選</a>
    <a class="button quiet" href="/keywords">調整或重跑關鍵字</a>
  </div>
  <p class="help">勾選關鍵字後會自動更新；多個關鍵字是「任一命中」就顯示。</p>
</form>
{auto_batch_panel}
<h2>批次處理</h2>
<div class="card batch-panel">
  <p><strong id="selected-count">已選取 0 則</strong></p>
  <div class="button-row">
    <button type="button" class="secondary" id="select-visible">{button_content("全選目前顯示", "select", "A")}</button>
    <button type="button" class="quiet" id="clear-selection">{button_content("清除選取", "clear", "L")}</button>
  </div>
  <form id="items-batch-form" method="post" action="/items/batch" data-batch-form>
    <input type="hidden" id="batch-ids" name="ids">
    <input type="hidden" id="batch-reason" name="reason">
    <div class="button-row">
      <button type="submit" name="action" value="accept">{button_content("批次確認收，準備跑 skill", "accept", "A")}</button>
      <button type="submit" name="action" value="direct_pr" class="secondary">{button_content("批次直接送 PR（小消息）", "small-news", "P")}</button>
    </div>
    <p class="help">批次不收原因</p>
    <div class="reason-presets">{batch_buttons}</div>
    <details class="inline-reason">
      <summary>批次其他原因</summary>
      <div class="button-row">
        <input id="batch-custom-reason" name="custom_reason" placeholder="寫一句批次不收原因">
        <button type="submit" name="action" value="reject" class="reason-chip reason-chip--danger" data-custom-reason="1">{button_content("用這個原因批次不收", "reject", "X")}</button>
      </div>
    </details>
  </form>
  <p class="help">批次處理只會處理你勾選的項目；處理完會從 RSS 待整理消失。</p>
  <p class="help">批次選到 RSS 新進時，系統會先寫進 database/items.jsonl，再套用確認收或直接送 PR；批次不收會寫入不收學習檔，RSS 新進也會寫入略過清單。</p>
</div>
<h2>RSS 待整理項目</h2>
<p class="muted">符合條件：{len(filtered)} 筆。{'' if show_all else f'目前先顯示 {len(visible)} 筆。'}</p>
{more_link}
<div class="list">{''.join(rows)}</div>
{more_link}
<script>
const itemCheckboxes = Array.from(document.querySelectorAll(".item-select"));
const batchIds = document.getElementById("batch-ids");
const batchReason = document.getElementById("batch-reason");
const selectedCount = document.getElementById("selected-count");
const customReason = document.getElementById("batch-custom-reason");

function liveCheckboxes() {{
  return itemCheckboxes.filter((box) => box.isConnected);
}}

function syncSelection() {{
  const ids = liveCheckboxes().filter((box) => box.checked).map((box) => box.value);
  batchIds.value = ids.join(",");
  selectedCount.textContent = `已選取 ${{ids.length}} 則`;
  return ids;
}}

itemCheckboxes.forEach((box) => box.addEventListener("change", syncSelection));
document.querySelectorAll("#items-filter-form .auto-filter, #items-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("items-filter-form").submit());
}});
document.getElementById("select-visible").addEventListener("click", () => {{
  liveCheckboxes().forEach((box) => {{ box.checked = true; }});
  syncSelection();
}});
document.getElementById("clear-selection").addEventListener("click", () => {{
  liveCheckboxes().forEach((box) => {{ box.checked = false; }});
  syncSelection();
}});

function buildRequestBody(form, submitter) {{
  let data;
  try {{
    data = new FormData(form, submitter);
  }} catch (error) {{
    data = new FormData(form);
    if (submitter?.name) {{
      data.append(submitter.name, submitter.value);
    }}
  }}
  const params = new URLSearchParams();
  data.forEach((value, key) => {{
    params.append(key, value);
  }});
  return params;
}}

function findItemCard(id) {{
  return Array.from(document.querySelectorAll(".candidate-card[data-item-id]")).find((card) => card.dataset.itemId === id);
}}

function removeCards(ids) {{
  const cards = ids
    .map((id) => findItemCard(id))
    .filter((card) => card && !card.classList.contains("is-removing"));
  if (!cards.length) {{
    return;
  }}
  cards.forEach((card) => {{
    card.classList.add("is-removing");
  }});
  window.setTimeout(() => {{
    cards.forEach((card) => {{
      if (card.isConnected) {{
        card.remove();
      }}
    }});
    syncSelection();
  }}, 260);
}}

async function submitWithoutLeaving(form, submitter, idsToRemove) {{
  const body = buildRequestBody(form, submitter);
  const fields = Array.from(form.querySelectorAll("button, input, select, textarea"));
  fields.forEach((field) => {{ field.disabled = true; }});
  try {{
    const targetUrl = form.getAttribute("action") || form.action;
    const method = form.getAttribute("method") || form.method || "POST";
    const response = await fetch(targetUrl, {{
      method,
      body,
      credentials: "same-origin",
      redirect: "follow",
      headers: {{ "X-Requested-With": "local-web-fetch" }},
    }});
    if (!response.ok) {{
      throw new Error(`HTTP ${{response.status}}`);
    }}
    removeCards(idsToRemove);
  }} catch (error) {{
    fields.forEach((field) => {{ field.disabled = false; }});
    alert("剛剛沒有送成功，畫面先保留。可以再按一次。");
  }}
}}

document.querySelectorAll("form[data-decision-form]").forEach((form) => {{
  form.addEventListener("submit", (event) => {{
    event.preventDefault();
    const reasonInput = form.querySelector("[name='reason']");
    if (form.dataset.requireReason !== undefined && !reasonInput?.value.trim()) {{
      alert("請先寫一句不收原因。");
      reasonInput?.focus();
      return;
    }}
    const itemId = form.querySelector("[name='id']")?.value;
    if (!itemId) {{
      return;
    }}
    submitWithoutLeaving(form, event.submitter, [itemId]);
  }});
}});

document.getElementById("items-batch-form").addEventListener("submit", (event) => {{
  event.preventDefault();
  const ids = syncSelection();
  const submitter = event.submitter;
  if (submitter?.dataset.batchReason) {{
    batchReason.value = submitter.dataset.batchReason;
  }} else if (submitter?.dataset.customReason) {{
    batchReason.value = customReason.value.trim();
  }}
  if (!ids.length) {{
    alert("請先勾選要處理的項目。");
    return;
  }}
  if (submitter?.value === "reject" && !batchReason.value.trim()) {{
    alert("請先選一個不收原因，或填寫其他原因。");
    customReason?.focus();
    return;
  }}
  submitWithoutLeaving(event.currentTarget, submitter, ids);
}});
</script>
"""
        self.send_html("RSS 待整理", body)

    def show_item_reject_form(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        items = load_jsonl(ITEMS)
        item = next((row for row in items if row.get("id") == item_id), None)
        if not item:
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        error = ""
        if (query.get("error") or [""])[0] == "reason":
            error = '<div class="notice">請先寫一點原因，再標記不收。</div>'
        reason_buttons = "\n".join(
            f'<button type="button" class="secondary reason-preset" data-reason="{h(reason)}">{h(reason)}</button>'
            for reason in prioritized_rejection_reasons(item, rejection_reason_options(items))
        )
        triage = item.get("triage") or {}
        body = f"""
<h1>不收原因</h1>
<p class="lede">這一步會把項目移出 items 主資料庫，存到 rejected-items 學習檔並保留原因。這些原因之後會出現在快捷按鈕裡，幫你更快整理不要看的資料。</p>
{error}
<article class="card candidate-card candidate-card--{h(candidate_recommendation(item))}">
  <div>
    {badge(track_meta(item.get("track", "unclassified"))["short"], track_class(item.get("track", "unclassified")))}
    {badge(recommendation_label(candidate_recommendation(item)), candidate_recommendation(item))}
    <strong><a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 420))}</p>
  <p class="help">系統判斷：{h(triage.get('reason', '未標示'))}</p>
</article>
<form class="form-panel" method="post" action="/items/reject">
  <input type="hidden" name="id" value="{h(item_id)}">
  <label>常用原因</label>
  <div class="reason-presets">{reason_buttons}</div>
  <p class="help">點一個原因會先放進文字框；你可以再補自己的判斷。</p>
  <label>這次不收的原因</label>
  <textarea id="reject-reason" name="reason" required></textarea>
  <p class="help">例：和主線關聯太弱、重複、只是活動公告、缺少可查證來源。這會寫進不收學習檔和 review event。</p>
  <div class="button-row">
    <button type="submit" class="danger">{button_content("確認不收並記錄原因", "reject", "X")}</button>
    <a class="button secondary" href="/items">先不要決定</a>
  </div>
</form>
<script>
document.querySelectorAll(".reason-preset").forEach((button) => {{
  button.addEventListener("click", () => {{
    const target = document.getElementById("reject-reason");
    target.value = button.dataset.reason;
    target.focus();
  }});
}});
</script>
"""
        self.send_html("不收原因", body)

    def show_candidates(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        skill_candidates = [item for item in items if is_skill_candidate(item)]
        track_filter = (query.get("track") or ["all"])[0]
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(item: dict) -> bool:
            return track_filter == "all" or item.get("track") == track_filter

        def matches(item: dict) -> bool:
            if not matches_basic(item):
                return False
            if selected_keywords and not (item_triage_keywords(item) & selected_keywords):
                return False
            return True

        keyword_source_items = [item for item in skill_candidates if matches_basic(item)]
        keyword_counts = Counter(keyword for item in keyword_source_items for keyword in item_triage_keywords(item))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)
        filtered_skill = [item for item in skill_candidates if matches(item)]
        filtered_skill.sort(
            key=lambda item: ((item.get("local_decision") or {}).get("decided_at", ""), item.get("captured_at", "")),
            reverse=True,
        )
        track_counts = Counter(item.get("track", "unclassified") for item in skill_candidates)
        skill_rows = []
        for item in filtered_skill:
            triage = item.get("triage") or {}
            recommendation = candidate_recommendation(item)
            css_class = track_class(item.get("track", "unclassified"))
            decided_at = (item.get("local_decision") or {}).get("decided_at", "未標示時間")
            detail_href = item_detail_href(item)
            skill_rows.append(
                f"""
<article class="card candidate-card">
  <div>
    {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
    {badge("待跑 skill", "neutral")}
    {badge(recommendation_label(recommendation), recommendation)}
    <strong><a href="{h(detail_href)}">{h(item_display_title(item))}</a></strong>
  </div>
  <p class="muted break-anywhere">{source_name_link(item)} · 確認收：{h(decided_at)} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a> · {h(item.get('url'))}</p>
  <p>{h(clean_text(item.get('summary'), 320))}</p>
  {editorial_triage_html(item, compact=True)}
  <p class="help">下一步：跑 skill 做摘要、切角與文章編修；整理好後再送 GitHub PR。<br>系統原判斷：{h(triage.get('reason', '未標示'))}</p>
</article>
"""
            )
        if not skill_rows:
            skill_rows.append('<div class="card"><strong>目前沒有待跑 skill 的項目</strong><p class="muted">在 RSS 待整理按「確認收」後，會移到這裡。</p></div>')

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        keyword_filters = []
        for keyword in keyword_options:
            checked = " checked" if keyword in selected_keywords else ""
            count = keyword_counts.get(keyword, 0)
            keyword_filters.append(
                f"""
<label class="keyword-option">
  <input type="checkbox" name="keyword" value="{h(keyword)}"{checked}>
  {h(keyword)} <span class="muted">({count})</span>
</label>
"""
            )
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用子關鍵字。</p>'

        def candidate_metric_href(track: str = "") -> str:
            params = []
            if track:
                params.append(("track", track))
            for keyword in sorted(selected_keywords):
                params.append(("keyword", keyword))
            return href_with_query("/candidates", params)

        body = f"""
<h1>候選清單</h1>
<p class="lede">這裡只放你已確認收下、準備跑 skill 編修的資料。RSS 剛抓到的新文章請回「RSS 待整理」處理。</p>
<div class="grid">
  {metric_card(len(skill_candidates), "待跑 skill", candidate_metric_href(), "看全部", "is-active" if track_filter == "all" else "")}
  {metric_card(track_counts.get("open-tech-open-industry", 0), "開放科技", candidate_metric_href("open-tech-open-industry"), "只看開放科技", "is-active" if track_filter == "open-tech-open-industry" else "")}
  {metric_card(track_counts.get("digital-humanities-local-knowledge", 0), "人文知識", candidate_metric_href("digital-humanities-local-knowledge"), "只看人文知識", "is-active" if track_filter == "digital-humanities-local-knowledge" else "")}
  {metric_card(track_counts.get("unclassified", 0), "未分類", candidate_metric_href("unclassified"), "只看未分類", "is-active" if track_filter == "unclassified" else "")}
</div>
<h2>篩選候選</h2>
<form class="filter-panel" method="get" action="/candidates" id="candidate-filter-form">
  <label>主線</label>
  <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
  <p class="help">選完會自動更新。處理完 skill 後，再把內容整理成 PR。</p>
  <label>子關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/items">回 RSS 待整理</a>
  </div>
  <p class="help">勾選子關鍵字後會自動更新；多個關鍵字是任一命中就顯示。</p>
</form>
<h2>已確認收，待跑 skill</h2>
<div class="list">{''.join(skill_rows)}</div>
<script>
document.querySelectorAll("#candidate-filter-form .auto-filter").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("candidate-filter-form").submit());
}});
document.querySelectorAll("#candidate-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => document.getElementById("candidate-filter-form").submit());
}});
</script>
"""
        self.send_html("候選清單", body)

    def show_reader(self, query: dict[str, list[str]]) -> None:
        items = [item for item in load_jsonl(ITEMS) if is_reader_item(item)]
        track_filter = (query.get("track") or ["all"])[0]
        kind_filter = (query.get("kind") or ["all"])[0]
        view_mode = (query.get("view") or ["auto"])[0]
        if view_mode not in {"auto", "card", "list", "compact"}:
            view_mode = "auto"
        time_filter = (query.get("time") or ["week"])[0]
        if time_filter not in {key for key, _ in READER_TIME_FILTERS}:
            time_filter = "week"
        start_date = clean_text((query.get("start") or [""])[0])
        end_date = clean_text((query.get("end") or [""])[0])
        time_start, time_end = reader_time_bounds(time_filter, start_date, end_date)
        selected_keywords = {keyword for keyword in (query.get("keyword") or []) if keyword}

        def matches_basic(item: dict) -> bool:
            if track_filter != "all" and item.get("track") != track_filter:
                return False
            kind = item_display_kind(item)
            if kind_filter != "all" and kind != kind_filter:
                return False
            return True

        def matches_scope(item: dict) -> bool:
            return matches_basic(item) and item_matches_time_filter(item, time_start, time_end)

        def matches(item: dict) -> bool:
            if not matches_scope(item):
                return False
            if selected_keywords and not (item_triage_keywords(item) & selected_keywords):
                return False
            return True

        keyword_source_items = [item for item in items if matches_scope(item)]
        keyword_counts = Counter(keyword for item in keyword_source_items for keyword in item_triage_keywords(item))
        keyword_options = [keyword for keyword, _ in keyword_counts.most_common(40)]
        for keyword in sorted(selected_keywords):
            if keyword not in keyword_options:
                keyword_options.insert(0, keyword)
        filtered = [item for item in items if matches(item)]
        filtered.sort(
            key=lambda item: (item_sort_time(item), item_display_title(item)),
            reverse=True,
        )
        if kind_filter == "all":
            kind_priority = {"featured-article": 0, "opinion-article": 1, "small-news": 2, "needs-review": 3}
            filtered.sort(key=lambda item: kind_priority.get(item_display_kind(item), 9))
        track_counts = Counter(item.get("track", "unclassified") for item in items)
        kind_counts = Counter(item_display_kind(item) for item in items)
        notice = ""
        if (query.get("saved") or [""])[0] == "read_more":
            notice = '<div class="notice">已嘗試載入原始主文與頁面資料；若抓到全文，已寫進閱讀資料庫。</div>'
        elif (query.get("error") or [""])[0] == "read_more":
            notice = '<div class="notice">這次沒有抓到更多資料，可能是網站擋住讀取、需要登入，或頁面沒有可抽取的主文。</div>'
        redirect_parts = []
        if track_filter != "all":
            redirect_parts.append(f"track={quote(track_filter)}")
        if kind_filter != "all":
            redirect_parts.append(f"kind={quote(kind_filter)}")
        if view_mode != "auto":
            redirect_parts.append(f"view={quote(view_mode)}")
        if time_filter != "week":
            redirect_parts.append(f"time={quote(time_filter)}")
        if time_filter == "custom":
            if start_date:
                redirect_parts.append(f"start={quote(start_date)}")
            if end_date:
                redirect_parts.append(f"end={quote(end_date)}")
        for keyword in sorted(selected_keywords):
            redirect_parts.append(f"keyword={quote(keyword)}")
        reader_redirect = "/reader" + (f"?{'&'.join(redirect_parts)}" if redirect_parts else "")

        def reader_card(item: dict, suffix: str = "card") -> str:
            css_class = track_class(item.get("track", "unclassified"))
            kind = item_display_kind(item)
            image = item_image_url(item)
            thumb = (
                f"<div class='reader-thumb'><img src='{h(image)}' alt=''></div>"
                if image
                else f"<div class='reader-thumb reader-thumb--{h(css_class)}'><span>{h(track_meta(item.get('track', 'unclassified'))['short'])}</span></div>"
            )
            note = personal_note_text(item)
            note_html = f"<p class='note-box'>{h(clean_text(note, 160))}</p>" if note else ""
            fulltext_id = f"fulltext-{suffix}-{h(item.get('id'))}"
            return f"""
<article class="card reader-card">
  {thumb}
  <div class="reader-body">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {badge(status_label(item.get("status", "")), "neutral")}
      {badge(content_kind_label(kind), "neutral")}
    </div>
    <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
    <p class="muted break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))}</p>
    <p class="zh-summary">{h(item_zh_summary(item, 260))}</p>
    {note_html}
    <div class="button-row reader-card-actions" aria-label="文章操作">
      <a class="button reader-action-button" href="{h(item_detail_href(item))}" aria-label="閱讀 / 記錄" title="閱讀 / 記錄">{icon_span("read", "O", "icon reader-action-icon")}{action_label("閱讀 / 記錄")}</a>
      <form method="post" action="/items/read-more" data-read-more-form data-target="#{fulltext_id}">
        <input type="hidden" name="id" value="{h(item.get('id'))}">
        <input type="hidden" name="redirect" value="{h(reader_redirect)}">
        <button type="submit" class="secondary reader-action-button" aria-label="展開全文" title="展開全文">{icon_span("expand", "E", "icon reader-action-icon")}{action_label("展開全文")}</button>
      </form>
      <a class="button secondary reader-action-button" href="{h(item.get('url'))}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{icon_span("external", "L", "icon reader-action-icon")}{action_label("原始連結")}</a>
    </div>
    <section class="fulltext-panel source-card source-card--source" id="{fulltext_id}" hidden>
      <div class="section-kicker">原始主文</div>
      <h3>剛載入的全文</h3>
      <p class="help" data-fulltext-meta></p>
      <div class="button-row" data-translation-actions hidden></div>
      <div class="article-text article-markdown" data-fulltext-body></div>
    </section>
  </div>
</article>
"""

        def reader_list_row(item: dict) -> str:
            kind = item_display_kind(item)
            return f"""
<article class="reader-list-card">
  <div class="reader-list-meta">
    {badge(content_kind_label(kind), "neutral")}
    {badge(item_display_time(item, 'published_at', 'captured_at'), "neutral")}
  </div>
  <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
  <p class="zh-summary">{h(item_zh_summary(item, 360))}</p>
</article>
"""

        def reader_compact_row(item: dict) -> str:
            return f"""
<article class="reader-compact-row">
  <span class="reader-dot" aria-hidden="true"></span>
  <h3><a href="{h(item_detail_href(item))}">{h(item_display_title(item))}</a></h3>
  <div class="reader-row-time">{h(item_display_time(item, 'published_at', 'captured_at'))}</div>
</article>
"""

        def reader_section(section_id: str, title: str, description: str, section_items: list[dict], default_layout: str) -> str:
            cards_html = "".join(reader_card(item, f"{section_id}-card") for item in section_items)
            list_html = "".join(reader_list_row(item) for item in section_items)
            compact_html = "".join(reader_compact_row(item) for item in section_items)
            empty = '<div class="card"><p class="muted">目前沒有符合這個區塊的文章。</p></div>'
            return f"""
<section class="reader-layout-section" id="{h(section_id)}" data-layout="{h(default_layout)}">
  <div class="layout-bar">
    <div>
      <h3>{h(title)}</h3>
      <p class="muted">{h(description)}</p>
    </div>
    {layout_toggle(section_id, default_layout)}
  </div>
  <div class="reader-grid">{cards_html or empty}</div>
  <div class="reader-list">{list_html or empty}</div>
  <div class="reader-compact-list">{compact_html or empty}</div>
</section>
"""

        visible_items = filtered[:180]
        if not visible_items:
            reader_content = '<div class="card"><strong>目前沒有符合條件的閱讀項目</strong><p class="muted">在 RSS 待整理按「確認收」或「直接送 PR（小消息）」後，會出現在這裡。</p></div>'
        else:
            if view_mode != "auto":
                reader_content = reader_section("reader-results", "文章", "目前篩選結果。", visible_items, view_mode)
            elif kind_filter == "small-news":
                reader_content = reader_section("reader-small-news", "小消息列表", "純新聞消息預設用列表快速掃讀，也可以切成卡片或清單。", visible_items, "list")
            elif kind_filter in {"featured-article", "opinion-article"}:
                reader_content = reader_section("reader-primary", "精選文章與觀點文章", "需要細讀、可能延伸撰稿或觀點整理的內容。", visible_items, "card")
            else:
                primary_items = [item for item in visible_items if item_display_kind(item) != "small-news"]
                news_items = [item for item in visible_items if item_display_kind(item) == "small-news"]
                reader_content = (
                    reader_section("reader-primary", "精選文章與觀點文章", "需要細讀、可能延伸撰稿或觀點整理的內容。", primary_items, "card")
                    + reader_section("reader-small-news", "小消息列表", "純新聞消息預設用列表快速掃讀，也可以切成卡片或清單。", news_items, "list")
                )

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        kind_options = [
            ("all", "全部類型"),
            ("featured-article", "精選文章 / 待跑 skill"),
            ("small-news", "純新聞 / 小消息"),
            ("opinion-article", "觀點文章"),
            ("needs-review", "人工判斷"),
        ]
        view_options = [("auto", "自動：分區預設"), ("card", "卡片"), ("list", "列表"), ("compact", "清單")]
        time_options = READER_TIME_FILTERS
        custom_hidden = "" if time_filter == "custom" else " hidden"
        custom_disabled = "" if time_filter == "custom" else " disabled"
        keyword_filters = []
        for keyword in keyword_options:
            checked = " checked" if keyword in selected_keywords else ""
            count = keyword_counts.get(keyword, 0)
            keyword_filters.append(
                f"""
<label class="keyword-option">
  <input type="checkbox" name="keyword" value="{h(keyword)}"{checked}>
  {h(keyword)} <span class="muted">({count})</span>
</label>
"""
            )
        keyword_filter_html = "".join(keyword_filters) if keyword_filters else '<p class="help">目前篩選條件下沒有可用子關鍵字。</p>'

        def reader_metric_href(track: str = "", kind: str = "") -> str:
            params = [("time", "all")]
            if track:
                params.append(("track", track))
            if kind:
                params.append(("kind", kind))
            return href_with_query("/reader", params)

        body = f"""
<h1>閱讀區</h1>
<p class="lede">這裡放已確認收下的精選文章與小消息。你可以像讀線上報一樣瀏覽，也可以在單篇頁留下「我的關鍵紀錄」，再把文章依你的觀點重新送回 skill。</p>
{notice}
<div class="grid">
  {metric_card(len(items), "可閱讀項目", reader_metric_href(), "看全部", "is-active" if track_filter == "all" and kind_filter == "all" and time_filter == "all" else "")}
  {metric_card(track_counts.get("open-tech-open-industry", 0), "開放科技", reader_metric_href(track="open-tech-open-industry"), "只看開放科技", "is-active" if track_filter == "open-tech-open-industry" else "")}
  {metric_card(track_counts.get("digital-humanities-local-knowledge", 0), "人文知識", reader_metric_href(track="digital-humanities-local-knowledge"), "只看人文知識", "is-active" if track_filter == "digital-humanities-local-knowledge" else "")}
  {metric_card(kind_counts.get("small-news", 0), "小消息", reader_metric_href(kind="small-news"), "只看小消息", "is-active" if kind_filter == "small-news" else "")}
</div>
<h2>篩選閱讀</h2>
<form class="filter-panel" method="get" action="/reader" id="reader-filter-form">
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track" class="auto-filter">{option_list(track_options, track_filter)}</select>
      <p class="help">分開閱讀開放科技或人文知識，也可以看全部。</p>
    </div>
    <div>
      <label>文章類型</label>
      <select name="kind" class="auto-filter">{option_list(kind_options, kind_filter)}</select>
      <p class="help">精選文章適合跑 skill；小消息多半只需要查核與短 PR。</p>
    </div>
    <div>
      <label>顯示格式</label>
      <select name="view" class="auto-filter">{option_list(view_options, view_mode)}</select>
      <p class="help">自動模式會讓精選與觀點優先用卡片，小消息優先用列表。</p>
    </div>
    <div>
      <label>時間</label>
      <select name="time" class="auto-filter" id="reader-time-filter">{option_list(time_options, time_filter)}</select>
      <p class="help">可看這三天、這週、最近 30 天、當季、今年、自定區間或全部。</p>
    </div>
    <div class="date-range-fields" data-time-custom-fields{custom_hidden}>
      <div>
        <label>開始日期</label>
        <input type="date" name="start" value="{h(start_date)}"{custom_disabled}>
      </div>
      <div>
        <label>結束日期</label>
        <input type="date" name="end" value="{h(end_date)}"{custom_disabled}>
      </div>
    </div>
  </div>
  <label>子關鍵字</label>
  <div class="keyword-filters">{keyword_filter_html}</div>
  <div class="button-row">
    <a class="button secondary" href="/reader">清除篩選</a>
    <a class="button quiet" href="/items">回 RSS 待整理</a>
  </div>
  <p class="help">勾選子關鍵字後會自動更新；多個關鍵字是任一命中就顯示。</p>
</form>
<h2>文章</h2>
<p class="muted">符合條件：{len(filtered)} 筆。時間：{h(reader_time_summary(time_filter, start_date, end_date))}。最多先顯示 180 筆，避免頁面太重。</p>
{reader_content}
<script>
const readerFilterForm = document.getElementById("reader-filter-form");
const readerTimeFilter = document.getElementById("reader-time-filter");
const readerTimeFields = document.querySelector("[data-time-custom-fields]");
function syncReaderTimeFields() {{
  if (!readerTimeFilter || !readerTimeFields) return;
  const isCustom = readerTimeFilter.value === "custom";
  readerTimeFields.hidden = !isCustom;
  readerTimeFields.querySelectorAll("input").forEach((field) => {{
    field.disabled = !isCustom;
  }});
}}
syncReaderTimeFields();
document.querySelectorAll("#reader-filter-form .auto-filter").forEach((field) => {{
  field.addEventListener("change", () => {{
    if (field === readerTimeFilter) {{
      syncReaderTimeFields();
      if (field.value === "custom" && !readerTimeFields.querySelector("input[value]:not([value=''])")) {{
        return;
      }}
    }}
    readerFilterForm.submit();
  }});
}});
document.querySelectorAll("#reader-filter-form input[type='checkbox']").forEach((field) => {{
  field.addEventListener("change", () => readerFilterForm.submit());
}});
document.querySelectorAll("[data-time-custom-fields] input").forEach((field) => {{
  field.addEventListener("change", () => readerFilterForm.submit());
}});
</script>
"""
        self.send_html("閱讀區", body)

    def show_item_detail(self, query: dict[str, list[str]]) -> None:
        item_id = form_value(query, "id")
        item = next((row for row in load_jsonl(ITEMS) if row.get("id") == item_id), None)
        is_rss_candidate = False
        if not item:
            item = next((row for row in load_jsonl(CANDIDATES) if row.get("id") == item_id), None)
            is_rss_candidate = bool(item)
            if not item:
                self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
                return
        item, _ = complete_item_metadata(item)

        saved = (query.get("saved") or [""])[0]
        notice = ""
        if saved == "note":
            notice = '<div class="notice">已更新你的個人關鍵紀錄。</div>'
        elif saved == "requeue":
            notice = '<div class="notice">已重新送回 skill 候選。你的個人觀點會留在紀錄裡，後續撰稿要一起參考。</div>'
        elif saved == "read_more":
            notice = '<div class="notice">已嘗試載入原始主文與頁面資料；若抓到全文，已寫入閱讀資料庫並顯示在「原始主文」。</div>'
        elif saved == "codex_review":
            notice = '<div class="notice">已補上 Codex 生成閱讀建議；如果有抓到全文，這次會優先依全文判斷。</div>'
        elif saved == "url":
            notice = '<div class="notice">已更新原始網址。接著可以按「展開全文」重新抓文章內容。</div>'
        elif saved == "title":
            notice = '<div class="notice">已更新這篇的對外顯示標題。</div>'
        elif saved == "metadata":
            notice = '<div class="notice">已更新這篇的原始 metadata。</div>'
        elif saved == "translation":
            notice = '<div class="notice">已完成中文翻譯，並存回閱讀資料庫。</div>'
        elif (query.get("error") or [""])[0] == "read_more":
            notice = '<div class="notice">這次沒有抓到更多資料。可能是網站擋住讀取、網址需要登入，或頁面沒有可抽取的主文。</div>'
        elif (query.get("error") or [""])[0] == "codex_review":
            notice = '<div class="notice">這次沒有順利補上 Codex 生成資訊。可以稍後再試，或先按「展開全文」補資料後再生成。</div>'
        elif (query.get("error") or [""])[0] == "url_resolve":
            notice = '<div class="notice">這次無法解析跳轉後網址。你仍可手動貼上實際文章網址再儲存。</div>'
        elif (query.get("error") or [""])[0] == "translation":
            notice = '<div class="notice">這次沒有順利翻譯。請先確認已展開全文，或稍後再試。</div>'

        css_class = track_class(item.get("track", "unclassified"))
        triage = item.get("triage") or {}
        kind = item_display_kind(item)
        image = item_image_url(item)
        image_html = (
            f"<div class='item-image'><img src='{h(image)}' alt=''></div>"
            if image
            else f"<div class='item-image'>{h(track_meta(item.get('track', 'unclassified'))['short'])}</div>"
        )
        article_text = item_article_text(item)
        article_markdown = item_article_markdown(item)
        article_html = markdown_to_html(article_markdown) if article_markdown else ""
        article_meta = item_reading_metadata(item)
        display_title = item_display_title(item)
        original_title = item_original_title(item)
        original_language = item_original_language(item)
        translated_markdown = item_translated_markdown(item)
        translated_html = markdown_to_html(translated_markdown) if translated_markdown else ""
        can_translate = bool(article_markdown or article_text) and is_foreign_language_item(item) and not translated_markdown and not is_rss_candidate
        translate_actions = (
            f"""
  <form method="post" action="/items/translate-zh">
    <input type="hidden" name="id" value="{h(item_id)}">
    <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
    <button type="submit" class="secondary">自動翻譯成中文</button>
  </form>
  <p class="help">偵測原文語言：{h(language_label(original_language))}{h(metadata_source_label(article_meta, "original_language"))}。會用台灣習慣用語翻成繁體中文，並存回本機資料庫。</p>
"""
            if can_translate
            else ""
        )
        translation_panel = (
            f"""
<section class="card fulltext-panel source-card source-card--source" id="translation-panel">
  <div class="section-kicker">Codex 中文翻譯</div>
  <h2>自動翻譯成中文</h2>
  <p class="help">翻譯來源：{h(article_meta.get('translation_source', 'Codex'))} · {h(article_meta.get('translation_generated_at', ''))}</p>
  <div class="article-text article-markdown">{translated_html}</div>
</section>
"""
            if translated_markdown
            else ""
        )
        fulltext_hidden = "" if article_markdown or article_text else " hidden"
        fulltext_message = (
            f"已載入 Markdown 閱讀版，約 {article_meta.get('article_markdown_chars', len(article_markdown)) or article_meta.get('article_text_chars', len(article_text))} 字；抽取方式：{article_meta.get('article_markdown_method') or article_meta.get('article_text_method', 'metadata')}。"
            if article_markdown or article_text
            else "按「展開全文」後會從原始連結往下抓全文，載入完成後以 Markdown 閱讀版顯示在這裡。"
        )
        note = personal_note_text(item)
        note_updated = ""
        personal_notes = item.get("personal_notes")
        if isinstance(personal_notes, dict) and personal_notes.get("updated_at"):
            note_updated = f"<p class='help'>上次更新：{h(personal_notes.get('updated_at'))}</p>"

        inbox_actions = ""
        if is_rss_candidate:
            reason_options = rejection_reason_options(load_jsonl(ITEMS))
            inbox_actions = f"""
<div class="card">
  <h2>RSS 新進決定</h2>
  <p class="muted">這則還在 RSS 新進。確認收或直接送 PR 時，系統會先寫進 database/items.jsonl，再套用你的決定；不收會寫入不收學習檔與略過清單。</p>
  <div class="button-row">
    <form method="post" action="/candidates/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="decision" value="accept">
      <button type="submit">{button_content("確認收，準備跑 skill", "accept", "A")}</button>
    </form>
    <form method="post" action="/candidates/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
      <input type="hidden" name="decision" value="direct_pr">
      <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
    </form>
  </div>
  <p class="help">不收原因</p>
  <div class="reason-presets">{inline_reject_buttons(item_id, prioritized_rejection_reasons(item, reason_options), action="/candidates/dismiss")}</div>
  <details class="inline-reason">
    <summary>其他原因</summary>
    <form method="post" action="/candidates/dismiss">
      <input type="hidden" name="id" value="{h(item_id)}">
      <label>這次不收的原因</label>
      <textarea name="reason" required></textarea>
      <button type="submit" class="danger">{button_content("確認不收並記錄原因", "reject", "X")}</button>
    </form>
  </details>
</div>
"""
        elif item.get("status") == "inbox":
            inbox_actions = f"""
<div class="card">
  <h2>待整理決定</h2>
  <p class="muted">這則還在待整理。可先直接分流；下方仍保留 Codex、來源與關鍵字判斷供比較。</p>
  <div class="button-row">
    <form method="post" action="/items/accept">
      <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit">{button_content("確認收，準備跑 skill", "accept", "A")}</button>
    </form>
    <form method="post" action="/items/direct-pr">
      <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit" class="secondary">{button_content("直接送 PR（小消息）", "small-news", "P")}</button>
    </form>
    <a class="button quiet" href="/items/reject?id={quote(item_id)}">{button_content("不收，寫原因", "reject", "X")}</a>
  </div>
  <p class="help">確認收會移到候選清單；直接送 PR 適合純事實小消息；不收會要求留下原因。</p>
</div>
"""

        skill_requests = item.get("skill_requests") if isinstance(item.get("skill_requests"), list) else []
        skill_rows = ""
        if skill_requests:
            rows = []
            for request in skill_requests[-5:]:
                rows.append(f"<li>{h(request.get('requested_at', ''))}：{h(clean_text(request.get('personal_notes'), 160))}</li>")
            skill_rows = f"<div class='card'><h2>重送 skill 紀錄</h2><ul>{''.join(rows)}</ul></div>"

        read_more_actions = f"""
      <form method="post" action="/items/read-more" data-read-more-form data-target="#fulltext-panel">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <button type="submit">展開全文</button>
      </form>
"""
        metadata_form = f"""
    <div class="card">
      <h2>原始 metadata</h2>
      <form method="post" action="/items/update-metadata">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <label>原始網站標題 {h(metadata_source_label(article_meta, "original_site_title"))}</label>
        <input name="original_site_title" value="{h(article_meta.get('original_site_title') or original_title)}" placeholder="原始網站標題">
        <label>原始語言 {h(metadata_source_label(article_meta, "original_language"))}</label>
        <input name="original_language" value="{h(original_language)}" placeholder="en / zh-Hant / ja">
        <p class="help">目前顯示：{h(language_label(original_language))}</p>
        <label>自動翻譯中文標題 {h(metadata_source_label(article_meta, "translated_zh_title"))}</label>
        <input name="translated_zh_title" value="{h(article_meta.get('translated_zh_title') or item_codex_zh_title(item))}" placeholder="翻譯後的中文標題">
        <label>原始作者 {h(metadata_source_label(article_meta, "original_author"))}</label>
        <input name="original_author" value="{h(article_meta.get('original_author') or item.get('author', ''))}" placeholder="作者或組織">
        <label>原始網站授權 {h(metadata_source_label(article_meta, "original_license"))}</label>
        <input name="original_license" value="{h(article_meta.get('original_license', ''))}" placeholder="Creative Commons / 著作權保護 / 未標示">
        <label>授權連結</label>
        <input name="original_license_url" value="{h(article_meta.get('original_license_url', ''))}" placeholder="https://...">
        <button type="submit">儲存 metadata</button>
      </form>
      <p class="help">標成「推斷」的欄位代表系統只從頁面字樣或內容比例判讀，仍可手動修正。</p>
    </div>
"""
        status_badge = badge("RSS 新進", "neutral") if is_rss_candidate else badge(status_label(item.get("status", "")), "neutral")
        body = f"""
<details class="title-editor">
  <summary>
    <h1>{h(display_title)}</h1>
    <span class="help">點擊標題可編輯；原始標題：{h(original_title)}</span>
  </summary>
  <form method="post" action="/items/update-title">
    <input type="hidden" name="id" value="{h(item_id)}">
    <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
    <label>對外顯示標題</label>
    <input name="title" value="{h(display_title)}" placeholder="輸入要顯示的中文標題">
    <button type="submit">儲存標題</button>
    <p class="help">留空儲存會清除人工標題，改回 Codex 中文標題或原始標題。</p>
  </form>
</details>
<p class="lede break-anywhere">{source_name_link(item)} · {h(item_display_time(item, 'published_at', 'captured_at'))} · {h(item.get('url'))}</p>
{notice}
<div class="item-hero">
  <section class="card">
    <div>
      {badge(track_meta(item.get("track", "unclassified"))["short"], css_class)}
      {status_badge}
      {badge(content_kind_label(kind), "neutral")}
      {badge(recommendation_label(candidate_recommendation(item)), candidate_recommendation(item))}
    </div>
    <p class="zh-summary">{h(item_zh_summary(item, 780))}</p>
    <p>{h(clean_text(item.get('summary'), 1800))}</p>
    <div class="button-row">
      {read_more_actions}
      <a class="button secondary" href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a>
      <a class="button quiet" href="/items">回 RSS 待整理</a>
      <a class="button quiet" href="/reader">回閱讀區</a>
    </div>
  </section>
  {image_html}
</div>

<section class="card fulltext-panel source-card source-card--source" id="fulltext-panel"{fulltext_hidden}>
  <div class="section-kicker">原始主文</div>
  <h2>展開全文載入的 Markdown 閱讀版</h2>
  <p class="help" data-fulltext-meta>{h(fulltext_message)}</p>
  <div class="article-text article-markdown" data-fulltext-body>{article_html}</div>
  <div class="button-row" data-translation-actions{'' if translate_actions else ' hidden'}>{translate_actions}</div>
</section>
{translation_panel}

<div class="two-column">
  <section>
    <h2>閱讀建議與判斷來源</h2>
    {inbox_actions}
    {editorial_triage_html(item, reject_action='/candidates/dismiss' if is_rss_candidate else '/items/reject')}
    <div class="card">
      <h2>關鍵字第一層判斷</h2>
      <p class="help">建議：{h(recommendation_label(candidate_recommendation(item)))}<br>理由：{h(triage.get('reason', '未標示'))}<br>命中：{h('、'.join(triage.get('matched_keywords') or []) or '無')}<br>排除：{h('、'.join(triage.get('skip_keywords') or []) or '無')}</p>
    </div>
    {skill_rows}
  </section>
  <aside>
    <div class="card">
      <h2>原始網址</h2>
      <p class="muted break-anywhere"><a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">{h(item.get('url') or '尚未填寫')}</a></p>
      <form method="post" action="/items/update-url">
        <input type="hidden" name="id" value="{h(item_id)}">
        <input type="hidden" name="redirect" value="{h(item_detail_href(item))}">
        <label>編輯原始網址</label>
        <input name="url" value="{h(item.get('url', ''))}" placeholder="https://example.com/article">
        <div class="button-row">
          <button type="submit" name="action" value="save">儲存網址</button>
          <button type="submit" name="action" value="resolve" class="secondary">帶入跳轉後網址</button>
        </div>
      </form>
      <p class="help">Google 快訊或追蹤網址如果會先跳轉，可先按「帶入跳轉後網址」，再展開全文。</p>
    </div>
    {metadata_form}
    {'' if is_rss_candidate else f'''
    <div class="card">
      <h2>我的關鍵紀錄</h2>
      <p class="muted">寫你自己的判斷、疑問或想補的觀點。之後按重新送 skill 時，agent 要用這段重新檢視文章。</p>
      <form method="post" action="/items/personal-note">
        <input type="hidden" name="id" value="{h(item_id)}">
        <textarea name="note" placeholder="例如：這篇和 OCF 的資料治理倡議有關，但要補台灣案例。">{h(note)}</textarea>
        <button type="submit">儲存我的紀錄</button>
      </form>
      {note_updated}
    </div>
    <div class="card">
      <h2>重新送 skill</h2>
      <p class="muted">如果讀完覺得這篇超值得整理，先寫好你的觀點，再按這顆。它會回到候選清單，等待用你的觀點跑撰稿 skill。</p>
      <form method="post" action="/items/requeue-skill">
        <input type="hidden" name="id" value="{h(item_id)}">
        <button type="submit">用我的觀點重新送 skill</button>
      </form>
      <p class="help">這不會自動發 PR，只會留下「重送 skill」紀錄並把狀態放回待跑 skill。</p>
    </div>
    '''}
  </aside>
</div>
"""
        self.send_html("單篇整理", body)

    def pop_candidate(self, candidate_id: str) -> dict | None:
        candidates = load_jsonl(CANDIDATES)
        candidate = None
        remaining = []
        for row in candidates:
            if row.get("id") == candidate_id and candidate is None:
                candidate = row
                continue
            remaining.append(row)
        if candidate is None:
            return None
        write_jsonl(CANDIDATES, remaining)
        return candidate

    def import_candidate_item(self, candidate_id: str) -> tuple[dict | None, bool]:
        candidate = self.pop_candidate(candidate_id)
        if candidate is None:
            return None, False
        item = remove_local_candidate_fields(candidate)
        items = load_jsonl(ITEMS)
        item_url = item.get("url")
        existing = next(
            (
                row
                for row in items
                if row.get("id") == item.get("id") or (item_url and row.get("url") == item_url)
            ),
            None,
        )
        if existing:
            return existing, True
        append_jsonl(ITEMS, item)
        return item, False

    def dismiss_candidate_record(self, candidate_id: str, reason: str = "") -> bool:
        candidate = self.pop_candidate(candidate_id)
        if candidate is None:
            return False
        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        notes = "RSS 待整理按鈕標記不收。"
        if reason:
            notes = f"{notes}原因：{reason}"
        archived_candidate = rejected_archive_record(
            {
                **candidate,
                "review": append_review_note(candidate.get("review") or {}, f"{decided_at} {notes}"),
            },
            decided_at,
            reason,
            ".cache/rss-candidates.jsonl",
        )
        item_url = clean_text(candidate.get("url"))
        active_items = load_jsonl(ITEMS)
        kept_items = []
        archived_active_items = []
        for item in active_items:
            if item.get("id") == candidate.get("id") or (item_url and clean_text(item.get("url")) == item_url):
                archived_active_items.append(
                    rejected_archive_record(
                        {
                            **item,
                            "review": append_review_note(item.get("review") or {}, f"{decided_at} {notes}"),
                        },
                        decided_at,
                        reason,
                    )
                )
            else:
                kept_items.append(item)
        if archived_active_items:
            write_jsonl(ITEMS, kept_items)
            for archived_item in archived_active_items:
                upsert_jsonl(REJECTED_ITEMS, archived_item)
        else:
            upsert_jsonl(REJECTED_ITEMS, archived_candidate)
        dismissed = {
            "id": candidate.get("id"),
            "track": candidate.get("track"),
            "title": candidate.get("title"),
            "url": candidate.get("url"),
            "source_id": candidate.get("source_id"),
            "source_name": candidate.get("source_name"),
            "reference": candidate.get("reference", {}),
            "triage": candidate.get("triage", {}),
            "dismissed_at": decided_at,
            "notes": notes,
        }
        if reason:
            dismissed["reason"] = reason
        append_jsonl(DISMISSED, dismissed)
        return True

    def update_pending_decisions(self, item_ids: list[str], action: str, reason: str = "") -> int:
        selected_ids = [item_id for item_id in item_ids if item_id]
        if not selected_ids:
            return 0

        candidate_ids = {row.get("id") for row in load_jsonl(CANDIDATES)}
        item_ids_to_update = []
        changed = 0
        for selected_id in selected_ids:
            if selected_id in candidate_ids:
                if action in {"accept", "direct_pr"}:
                    item, _already_exists = self.import_candidate_item(selected_id)
                    if item and item.get("id"):
                        item_ids_to_update.append(str(item.get("id")))
                elif action == "reject" and self.dismiss_candidate_record(selected_id, reason):
                    changed += 1
                continue
            item_ids_to_update.append(selected_id)

        if item_ids_to_update:
            changed += self.update_item_decisions(item_ids_to_update, action, reason)
        return changed

    def update_item_decisions(self, item_ids: list[str], action: str, reason: str = "") -> int:
        selected_ids = {item_id for item_id in item_ids if item_id}
        if not selected_ids:
            return 0

        items = load_jsonl(ITEMS)
        updated_items = []
        decided_at = now_iso()
        events = []
        changed = 0
        for item in items:
            if item.get("id") not in selected_ids or item.get("status") != "inbox":
                updated_items.append(item)
                continue
            updated_item = dict(item)
            if action == "accept":
                note = "本機確認收下；下一步跑 skill 做摘要、切角與文章編修，整理好後再送 PR。"
                event_status = "accepted-for-editing"
                updated_item["status"] = "triaged"
                updated_item["local_decision"] = {
                    "action": "accepted-for-editing",
                    "decided_at": decided_at,
                    "reason": "人工確認值得收，準備進入 skill 編修。",
                    "source": "local_web",
                    "next_step": "run-writing-skill-before-pr",
                }
            elif action == "direct_pr":
                note = "本機標記直接送 PR（小消息）；純事實項目，不跑 skill。"
                event_status = "direct-pr-small-news"
                updated_item["status"] = "ready"
                updated_item["local_decision"] = {
                    "action": "direct-pr-small-news",
                    "decided_at": decided_at,
                    "reason": "純事實小消息，直接送 PR。",
                    "source": "local_web",
                    "next_step": "direct-pr",
                }
            elif action == "reject":
                note = f"本機標記不收。原因：{reason}"
                event_status = "rejected"
                updated_item["status"] = "archived"
                updated_item["priority"] = "low"
                updated_item["local_decision"] = {
                    "action": "rejected",
                    "decided_at": decided_at,
                    "reason": reason,
                    "source": "local_web",
                }
            else:
                updated_items.append(item)
                continue
            updated_item["review"] = append_review_note(updated_item.get("review") or {}, f"{decided_at} {note}")
            if action == "reject":
                upsert_jsonl(REJECTED_ITEMS, rejected_archive_record(updated_item, decided_at, reason))
            else:
                updated_items.append(updated_item)
            events.append(review_event(updated_item, event_status, note))
            changed += 1

        if changed:
            write_jsonl(ITEMS, updated_items)
            for event in events:
                append_jsonl(REVIEW_EVENTS, event)
        return changed

    def accept_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "accept")
        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect(f"/items?saved=accepted&count={count}")

    def direct_pr_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "direct_pr")
        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect(f"/items?saved=direct_pr&count={count}")

    def reject_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        reason = form_value(data, "reason")
        if not reason:
            if self.is_async_request():
                self.send_no_content(HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/items?error=reason")
            return

        items = load_jsonl(ITEMS)
        if not any(item.get("id") == item_id for item in items):
            self.send_html("找不到項目", "<h1>找不到待整理項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        count = self.update_item_decisions([item_id], "reject", reason)
        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect(f"/items?saved=rejected&count={count}")

    def batch_items(self, data: dict[str, list[str]]) -> None:
        action = form_value(data, "action")
        raw_ids = ",".join(data.get("ids") or [])
        item_ids = [item_id.strip() for item_id in raw_ids.split(",") if item_id.strip()]
        if not item_ids:
            if self.is_async_request():
                self.send_no_content(HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/items?error=empty-selection")
            return
        if action == "accept":
            count = self.update_pending_decisions(item_ids, "accept")
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=accepted&count={count}")
            return
        if action == "direct_pr":
            count = self.update_pending_decisions(item_ids, "direct_pr")
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=direct_pr&count={count}")
            return
        if action == "reject":
            reason = form_value(data, "reason") or form_value(data, "custom_reason")
            if not reason:
                if self.is_async_request():
                    self.send_no_content(HTTPStatus.BAD_REQUEST)
                    return
                self.redirect("/items?error=reason")
                return
            count = self.update_pending_decisions(item_ids, "reject", reason)
            if self.is_async_request():
                self.send_no_content()
                return
            self.redirect(f"/items?saved=rejected&count={count}")
            return
        self.redirect("/items")

    def auto_batch_skip_items(self, data: dict[str, list[str]]) -> None:
        track_filter = form_value(data, "track", "all")
        selected_keywords = {keyword for keyword in (data.get("keyword") or []) if keyword}
        show_all = form_value(data, "show") == "all"
        candidates = load_jsonl(CANDIDATES)
        items = load_jsonl(ITEMS)
        inbox_items = [item for item in items if item.get("status") == "inbox"]
        pending_entries = [("rss", candidate) for candidate in candidates] + [("item", item) for item in inbox_items]

        def matches_auto_batch(record: dict) -> bool:
            if track_filter != "all" and record.get("track") != track_filter:
                return False
            if candidate_recommendation(record) != "suggest-skip":
                return False
            if selected_keywords and not (item_triage_keywords(record) & selected_keywords):
                return False
            return True

        targets = [record for _, record in pending_entries if matches_auto_batch(record)]
        count = 0
        for item in targets:
            item_id = clean_text(item.get("id"))
            if not item_id:
                continue
            reason = automatic_batch_rejection_reason(item)
            count += self.update_pending_decisions([item_id], "reject", reason)

        params = []
        if track_filter != "all":
            params.append(("track", track_filter))
        params.append(("recommendation", "suggest-skip"))
        for keyword in sorted(selected_keywords):
            params.append(("keyword", keyword))
        if show_all:
            params.append(("show", "all"))
        params.extend([("saved", "auto_rejected"), ("count", str(count))])
        self.redirect(href_with_query("/items", params))

    def save_personal_note(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        note = form_value(data, "note")
        items = load_jsonl(ITEMS)
        changed = False
        updated_items = []
        updated_at = now_iso()
        for item in items:
            if item.get("id") != item_id:
                updated_items.append(item)
                continue
            updated = dict(item)
            updated["personal_notes"] = {
                "body": note,
                "updated_at": updated_at,
                "source": "local_web",
            }
            updated_items.append(updated)
            changed = True
        if not changed:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(ITEMS, updated_items)
        self.redirect(f"/items/view?id={quote(item_id)}&saved=note")

    def requeue_skill_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        items = load_jsonl(ITEMS)
        changed = False
        updated_items = []
        requested_at = now_iso()
        event_item = None
        for item in items:
            if item.get("id") != item_id:
                updated_items.append(item)
                continue
            updated = dict(item)
            note = personal_note_text(updated)
            request = {
                "id": stable_id("skill-request", item_id, requested_at),
                "requested_at": requested_at,
                "source": "local_web",
                "personal_notes": note,
                "instruction": "重新用 personal_notes 檢視文章，補切角、摘要、查核重點與可採用觀點。",
            }
            skill_requests = updated.get("skill_requests") if isinstance(updated.get("skill_requests"), list) else []
            updated["skill_requests"] = [*skill_requests, request]
            updated["status"] = "triaged"
            updated["local_decision"] = {
                "action": "revisit-with-personal-notes",
                "decided_at": requested_at,
                "reason": "閱讀後人工要求用個人觀點重新跑 skill。",
                "source": "local_web",
                "next_step": "run-writing-skill-with-personal-notes",
            }
            updated["review"] = append_review_note(
                updated.get("review") or {},
                f"{requested_at} 閱讀後重新送 skill；個人觀點：{note or '未填'}",
            )
            updated_items.append(updated)
            event_item = updated
            changed = True
        if not changed or event_item is None:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(ITEMS, updated_items)
        append_jsonl(
            REVIEW_EVENTS,
            review_event(event_item, "revisit-with-personal-notes", "閱讀後重新送 skill，後續需納入 personal_notes。"),
        )
        self.redirect(f"/items/view?id={quote(item_id)}&saved=requeue")

    def update_read_more_record(self, path: Path, item_id: str) -> tuple[bool, bool, dict | None, str]:
        records = load_jsonl(path)
        changed = False
        found = False
        response_item: dict | None = None
        updated_records = []
        error = ""
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated, did_change, error = enrich_item_metadata(item)
            updated, markdown_changed = ensure_article_markdown(updated)
            updated_records.append(updated)
            changed = did_change or markdown_changed
            response_item = updated
        if found and changed:
            write_jsonl(path, updated_records)
        return found, changed, response_item, error

    def read_more_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"
        found, changed, response_item, error = self.update_read_more_record(ITEMS, item_id)
        found_in_items = found
        if not found:
            found, changed, response_item, error = self.update_read_more_record(CANDIDATES, item_id)
            found_in_items = False
        if not found:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/reader'>回閱讀區</a></p>", HTTPStatus.NOT_FOUND)
            return
        if wants_json:
            metadata = item_reading_metadata(response_item or {})
            article_text = clean_text(metadata.get("article_text"))
            article_markdown = clean_text(metadata.get("article_markdown")) or (
                text_to_markdown(article_text, title=metadata.get("title") or (response_item or {}).get("title") or "")
                if article_text
                else ""
            )
            article_html = markdown_to_html(article_markdown) if article_markdown else ""
            translation_actions_html = ""
            if found_in_items and response_item and article_markdown and is_foreign_language_item(response_item) and not item_translated_markdown(response_item):
                translation_actions_html = f"""
<form method="post" action="/items/translate-zh">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="redirect" value="{h(redirect_to)}">
  <button type="submit" class="secondary">自動翻譯成中文</button>
</form>
<p class="help">偵測原文語言：{h(language_label(item_original_language(response_item)))}{h(metadata_source_label(metadata, "original_language"))}。會用台灣習慣用語翻成繁體中文，並存回本機資料庫。</p>
"""
            message = (
                f"已載入 Markdown 閱讀版，約 {metadata.get('article_markdown_chars', len(article_markdown)) or metadata.get('article_text_chars', len(article_text))} 字；"
                f"抽取方式：{metadata.get('article_markdown_method') or metadata.get('article_text_method', 'metadata')}。"
                if article_markdown or article_text
                else "已嘗試讀取原始網址，但這次沒有抓到可顯示的主文。"
            )
            self.send_json(
                {
                    "ok": not bool(error) or bool(article_text) or bool(article_markdown),
                    "changed": changed,
                    "error": error,
                    "message": message,
                    "article_text": article_text,
                    "article_markdown": article_markdown,
                    "article_html": article_html,
                    "article_text_status": metadata.get("article_text_status", ""),
                    "article_markdown_status": metadata.get("article_markdown_status", ""),
                    "original_language": item_original_language(response_item or {}),
                    "can_translate": bool(translation_actions_html),
                    "translation_actions_html": translation_actions_html,
                    "image_url": metadata.get("image_url", ""),
                    "redirect": redirect_to,
                },
                HTTPStatus.OK if (not error or article_text or article_markdown) else HTTPStatus.BAD_GATEWAY,
            )
            return
        if changed:
            separator = "&" if "?" in redirect_to else "?"
            self.redirect(f"{redirect_to}{separator}saved=read_more")
            return
        separator = "&" if "?" in redirect_to else "?"
        if error:
            self.redirect(f"{redirect_to}{separator}error=read_more")
            return
        self.redirect(f"{redirect_to}{separator}saved=read_more")

    def codex_review_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"

        target = ""
        target_path = ITEMS
        if any(row.get("id") == item_id for row in load_jsonl(ITEMS)):
            target = "items"
            target_path = ITEMS
        elif any(row.get("id") == item_id for row in load_jsonl(CANDIDATES)):
            target = "candidates"
            target_path = CANDIDATES
        else:
            if wants_json:
                self.send_json({"ok": False, "error": "找不到項目"}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        if form_value(data, "with_fulltext", "1") == "1":
            self.update_read_more_record(target_path, item_id)

        command = [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--target",
            target,
            "--id",
            item_id,
            "--limit",
            "1",
            "--batch-size",
            "1",
        ]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=960)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
            ok = result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\nSTDERR:\n" + exc.stderr if exc.stderr else "")
            output = (output + "\nCodex 單篇生成逾時。").strip()
            ok = False
            result = subprocess.CompletedProcess(command, returncode=124, stdout="", stderr=output)

        separator = "&" if "?" in redirect_to else "?"
        final_redirect = f"{redirect_to}{separator}{'saved=codex_review' if ok else 'error=codex_review'}"
        if wants_json:
            self.send_json(
                {
                    "ok": ok,
                    "returncode": result.returncode,
                    "command": command,
                    "output": output,
                    "redirect": final_redirect,
                    "error": "" if ok else clean_text(output, 1000),
                },
                HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY,
            )
            return
        self.redirect(final_redirect)

    def update_url_record(self, path: Path, item_id: str, new_url: str, action: str) -> tuple[bool, str]:
        records = load_jsonl(path)
        updated_records = []
        found = False
        error = ""
        final_url = unwrap_google_alert_url(new_url)
        if action == "resolve":
            resolved, error = resolve_final_url(new_url)
            if resolved:
                final_url = resolved
        if not final_url:
            return False, error or "網址是空的。"
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            previous_url = clean_text(updated.get("url"))
            updated["url"] = final_url
            reference = updated.get("reference") if isinstance(updated.get("reference"), dict) else {}
            updated["reference"] = {
                **reference,
                "url_updated_at": updated_at,
                "url_update_source": "local_web",
                "previous_url": previous_url,
            }
            if action == "resolve":
                updated["reference"]["resolved_from_url"] = new_url
            metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
            if previous_url and previous_url != final_url:
                updated["reading_metadata"] = {
                    **metadata,
                    "url_before_update": previous_url,
                    "url_updated_at": updated_at,
                }
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found, error

    def update_item_url(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        new_url = form_value(data, "url")
        action = form_value(data, "action", "save")
        redirect_to = form_value(data, "redirect", f"/items/view?id={quote(item_id)}")
        if not redirect_to.startswith("/") or redirect_to.startswith("//"):
            redirect_to = f"/items/view?id={quote(item_id)}"
        found, error = self.update_url_record(ITEMS, item_id, new_url, action)
        if not found:
            found, error = self.update_url_record(CANDIDATES, item_id, new_url, action)
        if not found:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        if error and action == "resolve":
            self.redirect(f"{redirect_to}{separator}error=url_resolve")
            return
        self.redirect(f"{redirect_to}{separator}saved=url")

    def update_title_record(self, path: Path, item_id: str, title: str) -> bool:
        records = load_jsonl(path)
        updated_records = []
        found = False
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
            metadata = dict(metadata)
            clean_title = clean_text(title, 320)
            if clean_title:
                updated["editorial_title"] = clean_title
                metadata["editorial_title"] = clean_title
                metadata["editorial_title_source"] = "manual"
                metadata["editorial_title_updated_at"] = updated_at
            else:
                updated.pop("editorial_title", None)
                metadata.pop("editorial_title", None)
                metadata.pop("editorial_title_source", None)
                metadata["editorial_title_cleared_at"] = updated_at
            updated["reading_metadata"] = metadata
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found

    def update_item_title(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        title = form_value(data, "title")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        found = self.update_title_record(ITEMS, item_id, title)
        if not found:
            found = self.update_title_record(CANDIDATES, item_id, title)
        if not found:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=title")

    def update_metadata_record(self, path: Path, item_id: str, data: dict[str, list[str]]) -> bool:
        fields = [
            "original_site_title",
            "original_language",
            "translated_zh_title",
            "original_author",
            "original_license",
            "original_license_url",
        ]
        records = load_jsonl(path)
        updated_records = []
        found = False
        updated_at = now_iso()
        for item in records:
            if item.get("id") != item_id:
                updated_records.append(item)
                continue
            found = True
            updated = dict(item)
            metadata = updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {}
            metadata = dict(metadata)
            for field in fields:
                value = clean_text(form_value(data, field), 1200 if field != "translated_zh_title" else 320)
                metadata[field] = value
                if value:
                    metadata[f"{field}_source"] = "manual"
            metadata["metadata_updated_at"] = updated_at
            updated["reading_metadata"] = metadata
            updated_records.append(updated)
        if found:
            write_jsonl(path, updated_records)
        return found

    def update_item_metadata(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        found = self.update_metadata_record(ITEMS, item_id, data)
        if not found:
            found = self.update_metadata_record(CANDIDATES, item_id, data)
        if not found:
            self.send_html("找不到項目", "<h1>找不到項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=metadata")

    def translate_item_zh(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/items/view?id={quote(item_id)}")
        if not any(item.get("id") == item_id for item in load_jsonl(ITEMS)):
            self.send_html("找不到項目", "<h1>找不到可翻譯項目</h1><p><a class='button' href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return
        found, changed, response_item, error = self.update_read_more_record(ITEMS, item_id)
        article_markdown = item_article_markdown(response_item or {})
        if not found or (error and not article_markdown) or not article_markdown:
            separator = "&" if "?" in redirect_to else "?"
            self.redirect(f"{redirect_to}{separator}error=translation")
            return
        command = [
            sys.executable,
            str(ROOT / "scripts" / "codex_translate_article.py"),
            "--id",
            item_id,
        ]
        try:
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=1800)
            output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
            ok = result.returncode == 0
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + ("\nSTDERR:\n" + exc.stderr if exc.stderr else "")
            output = (output + "\nCodex 翻譯逾時。").strip()
            ok = False
        if not ok:
            print(output, file=sys.stderr)
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}{'saved=translation' if ok else 'error=translation'}")

    def preview_url(self, data: dict[str, list[str]]) -> None:
        url = form_value(data, "url")
        track = form_value(data, "track", "digital-humanities-local-knowledge")
        try:
            payload = build_url_preview(url, track)
        except Exception as exc:  # noqa: BLE001 - keep the local form from crashing on unusual pages.
            payload = {"ok": False, "error": str(exc)}
        self.send_json(payload, HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST)

    def accept_candidate(self, data: dict[str, list[str]]) -> None:
        candidate_id = form_value(data, "id")
        mode = form_value(data, "mode", "accept")
        decision = form_value(data, "decision")
        candidate_exists = any(row.get("id") == candidate_id for row in load_jsonl(CANDIDATES))
        if not candidate_exists:
            self.send_html("找不到候選項目", "<h1>找不到候選項目</h1><p><a href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        if decision in {"accept", "direct_pr"}:
            count = self.update_pending_decisions([candidate_id], decision)
            if self.is_async_request():
                self.send_no_content()
                return
            saved = "accepted" if decision == "accept" else "direct_pr"
            self.redirect(f"/items?saved={saved}&count={count}")
            return

        item, already_exists = self.import_candidate_item(candidate_id)
        if item is None:
            self.send_html("找不到候選項目", "<h1>找不到候選項目</h1><p><a href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return

        if mode == "accept_issue":
            returncode, output = create_github_issue(item)
            body = f"""
<h1>已收下候選項目</h1>
<p class="muted">資料庫：{'原本已存在，已從候選清單移除。' if already_exists else '已寫進 database/items.jsonl。'}</p>
<p class="muted">GitHub issue exit code: {returncode}</p>
<pre>{h(output)}</pre>
<p><a class="button" href="/items">回 RSS 待整理</a></p>
"""
            self.send_html("已收下候選項目", body)
            return

        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect("/items?saved=queued&count=1")

    def dismiss_candidate(self, data: dict[str, list[str]]) -> None:
        candidate_id = form_value(data, "id")
        reason = form_value(data, "reason")
        if not self.dismiss_candidate_record(candidate_id, reason):
            self.send_html("找不到候選項目", "<h1>找不到候選項目</h1><p><a href='/items'>回 RSS 待整理</a></p>", HTTPStatus.NOT_FOUND)
            return
        if self.is_async_request():
            self.send_no_content()
            return
        self.redirect("/items?saved=dismissed&count=1")

    def show_keywords(self) -> None:
        config = load_json(TRIAGE_KEYWORDS)
        track_sections = []
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge"]:
            meta = track_meta(track)
            track_config = (config.get("tracks") or {}).get(track, {})
            keep_keywords = "\n".join(track_config.get("keep_keywords") or [])
            skip_keywords = "\n".join(track_config.get("skip_keywords") or [])
            css_class = track_class(track)
            track_sections.append(
                f"""
<section class="card track-card track-card--{h(css_class)}">
  {badge(meta["short"], css_class)}
  <h2>{h(meta["label"])}</h2>
  <label>建議收的關鍵字</label>
  <textarea name="{h(track)}__keep_keywords">{h(keep_keywords)}</textarea>
  <p class="help">一行一個。候選文章標題、摘要、來源或標籤有命中，就會標成建議收。</p>
  <label>建議不要看的關鍵字</label>
  <textarea name="{h(track)}__skip_keywords">{h(skip_keywords)}</textarea>
  <p class="help">一行一個。命中這裡會優先標成建議不要看，例如交通管制、抽獎、停水。</p>
</section>
"""
            )
        body = f"""
<h1>篩選關鍵字</h1>
<p class="lede">這裡控制 RSS 待整理的第一層判斷，也會影響本機規則判斷欄位裡的「關鍵字匹配程度」。它不會刪資料，只會更新建議。</p>
<form method="post" action="/keywords">
  <div class="track-grid">{''.join(track_sections)}</div>
  <button type="submit">儲存關鍵字設定</button>
  <p class="help">儲存後會寫進 database/triage-keywords.json。下一次抓 RSS 時會套用。</p>
</form>
<div class="card">
  <h2>套用到目前待整理</h2>
  <p class="muted">如果你剛改完關鍵字，可以立刻重跑目前 RSS 新進與 database/items.jsonl 裡的 inbox 項目，並一起更新「三個建議看的理由」與初步收錄判斷。</p>
  <form method="post" action="/commands/run">
    <input type="hidden" name="command" value="apply_triage_keywords">
    <button type="submit" class="secondary">重新跑本機規則/關鍵字初篩</button>
  </form>
  <p class="help">這只更新 triage 與 editorial_triage 建議，不會自動收下、不會刪資料，也不會開 GitHub issue。</p>
</div>
"""
        self.send_html("篩選關鍵字", body)

    def save_keywords(self, data: dict[str, list[str]]) -> None:
        config = load_json(TRIAGE_KEYWORDS) or {"version": 1, "tracks": {}}
        config.setdefault("version", 1)
        config.setdefault("tracks", {})
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge"]:
            config["tracks"].setdefault(track, {"label": track_meta(track)["label"]})
            keep = [line.strip() for line in form_value(data, f"{track}__keep_keywords").split("\n") if line.strip()]
            skip = [line.strip() for line in form_value(data, f"{track}__skip_keywords").split("\n") if line.strip()]
            config["tracks"][track]["label"] = track_meta(track)["label"]
            config["tracks"][track]["keep_keywords"] = keep
            config["tracks"][track]["skip_keywords"] = skip
        write_json(TRIAGE_KEYWORDS, config)
        self.redirect("/keywords?saved=1")

    def quick_update_source(self, data: dict[str, list[str]]) -> None:
        source_id = form_value(data, "id")
        field = form_value(data, "field")
        value = form_value(data, "value")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), "/sources")
        allowed_values = {
            "status": SOURCE_STATUSES,
            "fetch_frequency": FETCH_FREQUENCIES,
        }
        if field not in allowed_values or value not in allowed_values[field]:
            self.send_html("欄位不允許", "<h1>欄位不允許</h1>", HTTPStatus.BAD_REQUEST)
            return
        sources = load_jsonl(SOURCES)
        updated_sources = []
        found = False
        for source in sources:
            if source.get("id") != source_id:
                updated_sources.append(source)
                continue
            updated = dict(source)
            updated[field] = value
            updated_sources.append(updated)
            found = True
        if not found:
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return
        write_jsonl(SOURCES, updated_sources)
        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=source_quick")

    def run_source_fetch(self, source_id: str) -> tuple[bool, str]:
        source = next((row for row in load_jsonl(SOURCES) if row.get("id") == source_id), {})
        report = ROOT / ".cache" / f"rss-fetch-{source_id}.md"
        command = [
            sys.executable,
            str(ROOT / "scripts" / "fetch_rss.py"),
            "--candidate-output",
            str(CANDIDATES),
            "--dismissed",
            str(DISMISSED),
            "--source-id",
            source_id,
            "--include-unclassified",
            "--force",
            "--report",
            str(report),
            "--status-file",
            str(RSS_FETCH_STATUS),
        ]
        source_type = clean_text(source.get("source_type"))
        if source_type in {"rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor"}:
            command.extend(["--source-type", source_type])
        source_track = clean_text(source.get("track"))
        if source_track:
            command.extend(["--track", source_track])
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=180)
        output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        return result.returncode == 0, output

    def fetch_source_now_post(self, data: dict[str, list[str]]) -> None:
        source_id = form_value(data, "id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/sources/view?id={quote(source_id)}")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        if not any(source.get("id") == source_id for source in load_jsonl(SOURCES)):
            if wants_json:
                self.send_json({"ok": False, "error": "找不到來源", "returncode": 1}, HTTPStatus.NOT_FOUND)
                return
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return
        ok, output = self.run_source_fetch(source_id)
        counts = source_fetch_counts(latest_source_fetch_stats(source_id))
        summary = source_fetch_summary_from_counts(counts)
        if wants_json:
            self.send_json(
                {
                    "ok": ok,
                    "label": "手動更新 RSS",
                    "returncode": 0 if ok else 1,
                    "summary": summary,
                    "output": output,
                    "redirect": redirect_to,
                    **counts,
                },
                HTTPStatus.OK,
            )
            return
        separator = "&" if "?" in redirect_to else "?"
        params = {"saved" if ok else "error": "source_fetch", **{key: str(value) for key, value in counts.items()}}
        self.redirect(f"{redirect_to}{separator}{urlencode(params)}")

    def rescan_source_keyword_exclusions(self, source: dict) -> dict[str, int]:
        source_id = clean_text(source.get("id"))
        if not source_id:
            return {"items": 0, "candidates": 0}
        decided_at = now_iso()
        reason = SOURCE_KEYWORD_EXCLUSION_REASON
        note = f"單一 RSS 來源關鍵字更新後重新盤點；排除原因：{reason}"

        items = load_jsonl(ITEMS)
        kept_items = []
        archived_items = []
        events = []
        for item in items:
            if item.get("source_id") != source_id or item.get("status") != "inbox" or source_record_passes_keywords(item, source):
                kept_items.append(item)
                continue
            updated = dict(item)
            updated["status"] = "archived"
            updated["priority"] = "low"
            updated["local_decision"] = {
                "action": "rejected",
                "decided_at": decided_at,
                "reason": reason,
                "source": "local_web_source_keywords",
            }
            updated["review"] = append_review_note(updated.get("review") or {}, f"{decided_at} {note}")
            archived_items.append(updated)
            events.append(review_event(updated, "rejected", note))
        if archived_items:
            write_jsonl(ITEMS, kept_items)
            for item in archived_items:
                upsert_jsonl(REJECTED_ITEMS, rejected_archive_record(item, decided_at, reason))
            for event in events:
                append_jsonl(REVIEW_EVENTS, event)

        candidate_ids = [
            clean_text(candidate.get("id"))
            for candidate in load_jsonl(CANDIDATES)
            if candidate.get("source_id") == source_id and not source_record_passes_keywords(candidate, source)
        ]
        dismissed_count = 0
        for candidate_id in candidate_ids:
            if candidate_id and self.dismiss_candidate_record(candidate_id, reason):
                dismissed_count += 1
        return {"items": len(archived_items), "candidates": dismissed_count}

    def restore_source_item(self, data: dict[str, list[str]]) -> None:
        item_id = form_value(data, "id")
        source_id = form_value(data, "source_id")
        redirect_to = safe_redirect_path(form_value(data, "redirect"), f"/sources/view?id={quote(source_id)}")
        rejected_records = load_jsonl(REJECTED_ITEMS)
        restored_record: dict | None = None
        kept_rejected = []
        for record in rejected_records:
            if record.get("id") == item_id and restored_record is None:
                restored_record = record
                continue
            kept_rejected.append(record)

        dismissed_records = load_jsonl(DISMISSED)
        kept_dismissed = []
        dismissed_record: dict | None = None
        for record in dismissed_records:
            if record.get("id") == item_id and dismissed_record is None:
                dismissed_record = record
                continue
            kept_dismissed.append(record)

        if restored_record is None:
            restored_record = dismissed_record
        if restored_record is None:
            self.send_html("找不到不收紀錄", "<h1>找不到不收紀錄</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return

        decided_at = now_iso()
        note = "從單一 RSS 來源的不收紀錄重新收錄，回到 RSS 待整理。"
        restored = dict(restored_record)
        for key in ["archive", "dismissed_at", "candidate_status", "reason"]:
            restored.pop(key, None)
        restored["status"] = "inbox"
        restored["priority"] = "normal"
        restored["local_decision"] = {
            "action": "restored",
            "decided_at": decided_at,
            "reason": "來源頁重新收錄",
            "source": "local_web",
            "next_step": "review-in-rss-inbox",
        }
        restored["review"] = append_review_note(restored.get("review") or {}, f"{decided_at} {note}")
        if source_id and not restored.get("source_id"):
            restored["source_id"] = source_id
        upsert_jsonl(ITEMS, restored)
        write_jsonl(REJECTED_ITEMS, kept_rejected)
        write_jsonl(DISMISSED, kept_dismissed)
        append_jsonl(REVIEW_EVENTS, review_event(restored, "restored", note))

        separator = "&" if "?" in redirect_to else "?"
        self.redirect(f"{redirect_to}{separator}saved=restored")

    def show_track(self, track: str) -> None:
        if track not in TRACK_META:
            self.send_html("找不到主線", "<h1>找不到這條知識主線</h1>", HTTPStatus.NOT_FOUND)
            return

        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        candidates = load_jsonl(CANDIDATES)
        meta = track_meta(track)
        css_class = track_class(track)
        button_class = f"button-{css_class}" if css_class in {"opentech", "humanities"} else "secondary"
        track_items = [item for item in items if item.get("track") == track]
        inbox_items = [item for item in track_items if item.get("status") == "inbox"]
        pending_items = [*inbox_items, *[item for item in candidates if item.get("track") == track]]
        track_sources = [source for source in sources if source.get("track") == track and source.get("status") != "archived"]
        fetchable_sources = [source for source in track_sources if is_fetchable_source(source)]
        source_types = Counter(source.get("source_type", "manual") for source in track_sources)
        source_groups = Counter(source.get("source_group", "未標示群組") for source in track_sources)
        recent_items = sorted(
            pending_items,
            key=lambda item: (item_sort_time(item), item_display_title(item)),
            reverse=True,
        )[:12]

        item_rows = []
        for item in recent_items:
            title = item_display_title(item)
            source_name = item.get("source_name") or item.get("author") or "未標示來源"
            captured = item_display_time(item, "captured_at", "published_at")
            detail_href = item_detail_href(item)
            item_rows.append(
                f"""
<div class="list-item list-item--{h(css_class)}">
  <strong><a href="{h(detail_href)}">{h(title)}</a></strong>
  <p class="muted">{source_name_link(item) if item.get('source_id') else h(source_name)} · {h(captured)} · <a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">原始連結</a></p>
  <p class="break-anywhere">{h(clean_text(item.get('summary'), 180))}</p>
</div>
"""
            )
        if not item_rows:
            item_rows.append('<div class="list-item"><strong>目前沒有待整理項目</strong><p class="muted">等下一次 RSS 抓取或手動收藏後，會出現在這裡。</p></div>')

        type_rows = []
        for source_type, count in source_types.most_common():
            safe_type = source_type.replace("_", "-")
            type_rows.append(
                f"<p>{badge(source_type_label(source_type), safe_type)} <strong>{count}</strong> 個來源<br><span class='help'>{h(SOURCE_TYPE_HELP.get(source_type, '這類來源目前只作為分類註記。'))}</span></p>"
            )
        group_rows = []
        for group, count in source_groups.most_common(10):
            group_rows.append(f"<li>{h(group)} <span class='muted'>({count})</span></li>")

        body = f"""
<h1>{h(meta["label"])}</h1>
<p class="lede">{h(meta["description"])}</p>
<div class="card track-card track-card--{h(css_class)}">
  {badge(meta["short"], css_class)}
  <div class="metric-row">
    {metric_tile(len(track_items), "全部項目", href_with_query("/reader", [("track", track), ("time", "all")]), "看閱讀")}
    {metric_tile(len(pending_items), "待整理", href_with_query("/items", [("track", track)]), "篩選待整理")}
    {metric_tile(len(track_sources), "來源", href_with_query("/sources", [("track", track)]), "看來源")}
    {metric_tile(len(fetchable_sources), "會自動抓", href_with_query("/sources", [("track", track), ("status", "active")]), "只看啟用")}
  </div>
  <div class="button-row">
    <a class="button {h(button_class)}" href="/items/new?track={quote(track)}">幫這條主線加收藏</a>
    <a class="button secondary" href="/sources/new?track={quote(track)}">幫這條主線加 RSS</a>
    <a class="button quiet" href="/sources?track={quote(track)}">看這條主線的來源</a>
  </div>
  <p class="help">加收藏是單篇文章或頁面；加 RSS 是長期追蹤一個網站或 feed；看來源可以檢查目前追蹤清單。</p>
</div>

<div class="two-column">
  <section>
    <h2>待整理項目</h2>
    <div class="list">{''.join(item_rows)}</div>
  </section>
  <aside>
    <h2>來源分類</h2>
    <div class="card">
      {''.join(type_rows) if type_rows else '<p class="muted">這條主線目前還沒有來源。</p>'}
    </div>
    <h2>常見來源群組</h2>
    <div class="card">
      <ul>{''.join(group_rows) if group_rows else '<li class="muted">還沒有來源群組。</li>'}</ul>
    </div>
  </aside>
</div>
"""
        self.send_html(meta["label"], body)

    def show_item_form(self, query: dict[str, list[str]]) -> None:
        title = clean_text(unquote((query.get("title") or [""])[0]))
        url = clean_text(unquote((query.get("url") or [""])[0]))
        current_track = (query.get("track") or ["digital-humanities-local-knowledge"])[0]
        if current_track not in TRACK_META:
            current_track = "digital-humanities-local-knowledge"
        body = f"""
<h1>加入收藏</h1>
<p class="lede">用在你看到一篇文章、一個頁面或一個案例，想先丟進 RSS 待整理時。這裡新增的是單筆知識項目，不是長期 RSS 來源。</p>
<form class="form-panel" method="post" action="/items" data-url-preview-form data-preview-kind="item">
  <label>主線</label>
  <select name="track" data-preview-track>{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定它會出現在「開放科技」或「人文與在地知識」哪一個工作台。</p>
  <label>標題</label>
  <input name="title" value="{h(title)}" required data-preview-title>
  <p class="help">通常用原本網頁標題就好，之後審稿時再改成更清楚的標題。</p>
  <label>網址</label>
  <input name="url" value="{h(url)}" required data-preview-url placeholder="https://example.com/article">
  <p class="help">網址很長也沒關係，列表會自動換行。</p>
  <div class="preview-panel" data-preview-panel hidden>
    <div class="preview-status" data-preview-status>等待網址。</div>
    <div class="preview-result" data-preview-result></div>
  </div>
  <button type="button" class="secondary" data-preview-button>{button_content("抓取頁面資訊", "preview", "M")}</button>
  <label>來源 / 網站 / 作者</label>
  <input name="source_name" placeholder="例如：報導者、Open Knowledge Foundation" data-preview-source-name>
  <p class="help">不知道作者時，先填網站或組織名稱。</p>
  <label>發布日期</label>
  <input name="published_at" placeholder="YYYY-MM-DD">
  <p class="help">不確定可以留空，之後整理時再補。</p>
  <label>摘要或摘記</label>
  <textarea name="summary" data-preview-summary></textarea>
  <p class="help">先貼一兩句你覺得重要的脈絡，方便未來審稿時想起來為什麼收。</p>
  <label>標籤</label>
  <input name="tags" placeholder="用逗號分隔">
  <p class="help">例如：開放資料, 地方創生, 博物館；不用一開始就很完整。</p>
  <label>備註 / 為什麼值得追</label>
  <textarea name="notes"></textarea>
  <p class="help">寫給未來的自己看：這則資料可能放進哪個議題、有哪些疑問。</p>
  <button type="submit">把這頁存進待整理</button>
  <p class="help">送出後會寫進 database/items.jsonl，狀態是 inbox，還不會自動發布。</p>
</form>
"""
        self.send_html("加入收藏", body)

    def save_item(self, data: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        url = unwrap_google_alert_url(form_value(data, "url"))
        title = form_value(data, "title") or url
        if any(item.get("url") == url for item in items):
            self.send_html("已存在", f"<h1>這個網址已經在資料庫</h1><p>{h(url)}</p><p><a href='/'>回總覽</a></p>")
            return
        source_name = form_value(data, "source_name") or "Manual bookmark"
        track = form_value(data, "track", "unclassified")
        source_id = stable_id("src", "manual-web", source_name)
        if not any(source.get("id") == source_id for source in sources):
            append_jsonl(
                SOURCES,
                {
                    "id": source_id,
                    "track": track,
                    "name": source_name,
                    "source_group": "Manual web bookmark",
                    "source_type": "manual",
                    "fetch_frequency": "daily",
                    "feed_url": "",
                    "site_url": "",
                    "status": "active",
                    "required_keywords": [],
                    "excluded_keywords": [],
                    "notes": "由本機網頁加入。",
                },
            )
        tags = [tag.strip() for tag in form_value(data, "tags").split(",") if tag.strip()]
        notes = form_value(data, "notes")
        record = {
            "id": stable_id("item", "manual-web", url, title),
            "track": track,
            "status": "inbox",
            "priority": "normal",
            "title": title,
            "url": url,
            "source_id": source_id,
            "source_name": source_name,
            "author": source_name,
            "published_at": form_value(data, "published_at"),
            "captured_at": now_iso(),
            "summary": form_value(data, "summary"),
            "tags": tags,
            "origin": "manual-web",
            "reference": {"created_by": "local_web"},
            "review": default_review(notes),
        }
        enriched, did_change, _ = enrich_item_metadata(record)
        if did_change:
            metadata = item_reading_metadata(enriched)
            if title == url and metadata.get("title"):
                enriched["title"] = clean_text(metadata.get("title"), 300)
            record = enriched
        append_jsonl(ITEMS, record)
        self.redirect("/?saved=item")

    def show_sources(self, query: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        items = load_jsonl(ITEMS)
        rejected_items = load_jsonl(REJECTED_ITEMS)
        candidates = load_jsonl(CANDIDATES)
        dismissed = load_jsonl(DISMISSED)
        track_filter = (query.get("track") or ["all"])[0]
        type_filter = (query.get("source_type") or ["all"])[0]
        status_filter = (query.get("status") or ["live"])[0]

        def matches(source: dict) -> bool:
            if track_filter != "all" and source.get("track") != track_filter:
                return False
            if type_filter != "all" and source.get("source_type") != type_filter:
                return False
            status = source.get("status")
            if status_filter == "live":
                return status != "archived"
            if status_filter != "all" and status != status_filter:
                return False
            return True

        filtered_sources = [source for source in sources if matches(source)]
        redirect_path = self.path

        def inline_source_select(source: dict, field: str, options: list[tuple[str, str]], current: str) -> str:
            return f"""
<form class="inline-select-form" method="post" action="/sources/quick-update">
  <input type="hidden" name="id" value="{h(source.get('id', ''))}">
  <input type="hidden" name="field" value="{h(field)}">
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <select name="value" aria-label="{h(field)}" onchange="this.form.submit()">{option_list(options, current)}</select>
</form>
"""

        def source_fetch_button(source: dict) -> str:
            return f"""
<form class="chip-form" method="post" action="/sources/fetch" data-source-fetch-form>
  <input type="hidden" name="id" value="{h(source.get('id', ''))}">
  <input type="hidden" name="redirect" value="{h(redirect_path)}">
  <button type="submit" class="reason-chip" title="手動更新這個 RSS">更新</button>
</form>
"""

        track_counts = {track: count_sources(sources, track) for track in TRACK_ORDER}
        fetch_counts = {track: count_sources(sources, track, active_only=True) for track in TRACK_ORDER}
        type_counts = Counter(source.get("source_type", "manual") for source in filtered_sources)
        grouped: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for source in filtered_sources:
            track = source.get("track", "unclassified")
            group = source.get("source_group", "未標示群組")
            grouped[track][group].append(source)

        type_summary = []
        for source_type, count in type_counts.most_common():
            safe_type = source_type.replace("_", "-")
            type_summary.append(f"{badge(source_type_label(source_type), safe_type)} <span class='muted'>{count}</span>")

        source_sections = []
        ordered_tracks = [track for track in TRACK_ORDER if track in grouped]
        ordered_tracks.extend(sorted(track for track in grouped if track not in ordered_tracks))
        for track in ordered_tracks:
            meta = track_meta(track)
            css_class = track_class(track)
            source_sections.append(f"<h2>{badge(meta['short'], css_class)} {h(meta['label'])}</h2>")
            for group, group_sources in sorted(grouped[track].items()):
                rows = []
                for source in sorted(group_sources, key=lambda row: (row.get("name", ""), row.get("id", ""))):
                    source_type = source.get("source_type", "manual")
                    status = source.get("status", "")
                    frequency = source.get("fetch_frequency", "daily")
                    feed_url = source.get("feed_url") or ""
                    site_url = source.get("site_url") or ""
                    type_class = source_type.replace("_", "-")
                    status_class = status.replace("_", "-")
                    health = source_health_summary(source, items, rejected_items, candidates, dismissed)
                    site_link = ""
                    if site_url:
                        site_link = f'<br><a class="muted break-anywhere" href="{h(site_url)}" target="_blank" rel="noreferrer">{h(site_url)}</a>'
                    feed_display = '<span class="muted">沒有 feed URL</span>'
                    if feed_url:
                        feed_display = f'<code class="url">{h(feed_url)}</code>'
                    rows.append(
                        "<tr>"
                        f"<td><strong><a href='/sources/view?id={quote(source.get('id', ''))}'>{h(source.get('name'))}</a></strong>"
                        f"{site_link}</td>"
                        f"<td>{badge(source_type_label(source_type), type_class)}</td>"
                        f"<td>{inline_source_select(source, 'status', [(value, SOURCE_STATUS_LABELS.get(value, value)) for value in SOURCE_STATUSES], status)}</td>"
                        f"<td>{inline_source_select(source, 'fetch_frequency', [(value, FETCH_FREQUENCY_LABELS.get(value, value)) for value in FETCH_FREQUENCIES], frequency)}</td>"
                        f"<td>{source_health_badge(health)}<br><span class='help'>{h(health.get('reason'))}</span></td>"
                        f"<td class='url-cell'>{feed_display}</td>"
                        f"<td><div class='source-action-row'><a class='reason-chip' href='/sources/edit?id={quote(source.get('id', ''))}'>編輯</a>{source_fetch_button(source)}</div></td>"
                        "</tr>"
                    )
                source_sections.append(
                    f"""
<details class="source-group" open>
  <summary>{h(group)} <span class="muted">({len(group_sources)})</span></summary>
  <table>
    <thead><tr><th>名稱</th><th>類型</th><th>狀態</th><th>頻率</th><th>健康狀態</th><th>Feed URL</th><th></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</details>
"""
                )
        if not source_sections:
            source_sections.append('<div class="card"><strong>沒有符合條件的來源</strong><p class="muted">換一個篩選條件，或新增 RSS 來源。</p></div>')

        track_options = [("all", "全部主線")] + [(track, TRACK_META[track]["label"]) for track in TRACK_ORDER]
        type_options = [("all", "全部來源類型")] + [(value, SOURCE_TYPE_LABELS.get(value, value)) for value in SOURCE_TYPES]
        status_options = [
            ("live", "啟用＋暫停"),
            ("active", "只看啟用"),
            ("paused", "只看暫停"),
            ("archived", "只看封存"),
            ("all", "全部狀態"),
        ]
        overview_cards = []
        for track in ["open-tech-open-industry", "digital-humanities-local-knowledge", "unclassified"]:
            meta = track_meta(track)
            css_class = track_class(track)
            overview_cards.append(
                f"""
<div class="card track-card track-card--{h(css_class)}">
  {badge(meta["short"], css_class)}
  <div class="metric-row">
    {metric_tile(track_counts.get(track, 0), "來源", href_with_query("/sources", [("track", track)]), "看來源")}
    {metric_tile(fetch_counts.get(track, 0), "會自動抓", href_with_query("/sources", [("track", track), ("status", "active")]), "只看啟用")}
  </div>
  <p class="help">會自動抓代表狀態是啟用，且類型是 RSS、Google 快訊、YouTube 或 Podcast。</p>
</div>
"""
            )
        notice = ""
        saved = form_value(query, "saved")
        error = form_value(query, "error")
        if saved == "source_quick":
            notice = '<div class="notice">來源欄位已更新。</div>'
        elif saved == "source_fetch":
            notice = f'<div class="notice">已手動更新這個 RSS。{h(source_fetch_summary_from_query(query))}新的項目會進 RSS 待整理。</div>'
        elif error == "source_fetch":
            notice = f'<div class="notice">手動更新沒有成功。{h(source_fetch_summary_from_query(query))}請進來源檢視頁看健康狀態或錯誤訊息。</div>'
        body = f"""
<h1>RSS 來源分類</h1>
{notice}
<p class="lede">這裡管理每天會被自動抓取或人工保留追蹤的來源。預設不顯示封存來源；你可以用篩選器切換主線、來源類型和狀態。</p>
<div class="grid">{''.join(overview_cards)}</div>
<h2>篩選來源</h2>
<form class="filter-panel" method="get" action="/sources">
  <div class="form-grid">
    <div>
      <label>主線</label>
      <select name="track">{option_list(track_options, track_filter)}</select>
      <p class="help">用來分開看開放科技、人文與在地知識，或未分類來源。</p>
    </div>
    <div>
      <label>來源類型</label>
      <select name="source_type">{option_list(type_options, type_filter)}</select>
      <p class="help">RSS / Google 快訊 / YouTube / Podcast 會被抓取；Facebook 與 Inoreader 目前保留作對照。</p>
    </div>
    <div>
      <label>狀態</label>
      <select name="status">{option_list(status_options, status_filter)}</select>
      <p class="help">啟用會進入抓取流程；暫停先保留但不抓；封存是歷史資料。</p>
    </div>
  </div>
  <div class="button-row">
    <button type="submit">套用篩選</button>
    <a class="button secondary" href="/sources/new{('?track=' + quote(track_filter)) if track_filter != 'all' else ''}">新增 RSS 來源</a>
  </div>
  <p class="help">篩選只改變畫面，不會改資料。新增 RSS 才會寫入 database/sources.jsonl。</p>
</form>
<h2>目前列表</h2>
<p class="muted">符合條件：{len(filtered_sources)} 個來源。{''.join(type_summary) if type_summary else ''}</p>
{''.join(source_sections)}
"""
        self.send_html("RSS 來源", body)

    def show_source_view(self, query: dict[str, list[str]]) -> None:
        source_id = form_value(query, "id")
        sources = load_jsonl(SOURCES)
        source = next((row for row in sources if row.get("id") == source_id), None)
        if not source:
            self.send_html("找不到來源", "<h1>找不到來源</h1><p><a class='button' href='/sources'>回 RSS 來源</a></p>", HTTPStatus.NOT_FOUND)
            return

        items = [item for item in load_jsonl(ITEMS) if item.get("source_id") == source_id]
        candidates = [item for item in load_jsonl(CANDIDATES) if item.get("source_id") == source_id]
        rejected = [item for item in load_jsonl(REJECTED_ITEMS) if item.get("source_id") == source_id]
        dismissed = [item for item in load_jsonl(DISMISSED) if item.get("source_id") == source_id]
        health = source_health_summary(source, load_jsonl(ITEMS), load_jsonl(REJECTED_ITEMS), load_jsonl(CANDIDATES), load_jsonl(DISMISSED))

        def sort_items(records: list[dict]) -> list[dict]:
            return sorted(
                records,
                key=lambda item: (item_sort_time(item), item_display_title(item)),
                reverse=True,
            )

        def source_summary(item: dict, archived: bool = False, limit: int = 260) -> str:
            if archived:
                decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
                return clean_text(item.get("reason") or decision.get("reason") or item.get("notes"), limit)
            return item_zh_summary(item, limit)

        def restore_form(item: dict) -> str:
            item_id = clean_text(item.get("id"))
            if not item_id:
                return ""
            return f"""
<form class="chip-form" method="post" action="/sources/restore-item">
  <input type="hidden" name="id" value="{h(item_id)}">
  <input type="hidden" name="source_id" value="{h(source_id)}">
  <input type="hidden" name="redirect" value="/sources/view?id={h(quote(source_id))}#source-rejected">
  <button type="submit" class="reason-chip">重新收錄</button>
</form>
"""

        def source_list_row(item: dict, can_open: bool = True, archived: bool = False) -> str:
            kind = item_display_kind(item)
            item_url = clean_text(item.get("url"))
            title = item_display_title(item)
            if archived and item_url:
                title_html = f'<a href="{h(item_url)}" target="_blank" rel="noreferrer">{h(title)}</a>'
            elif can_open:
                title_html = f'<a href="{h(item_detail_href(item))}">{h(title)}</a>'
            else:
                title_html = h(title)
            summary = source_summary(item, archived, 240)
            return f"""
<article class="reader-list-card">
  <div class="reader-list-meta">
    {badge("不收紀錄", "suggest-skip") if archived else badge(content_kind_label(kind), "neutral")}
    {badge(item_display_time(item, 'published_at', 'captured_at', 'dismissed_at'), "neutral")}
  </div>
  <h3>{title_html}</h3>
  <p class="zh-summary">{h(summary)}</p>
  {f'<div class="source-action-row">{restore_form(item)}</div>' if archived else ''}
</article>
"""

        def source_compact_row(item: dict, can_open: bool = True, archived: bool = False) -> str:
            item_url = clean_text(item.get("url"))
            title = item_display_title(item)
            if archived and item_url:
                title_html = f'<a href="{h(item_url)}" target="_blank" rel="noreferrer">{h(title)}</a>'
            elif can_open:
                title_html = f'<a href="{h(item_detail_href(item))}">{h(title)}</a>'
            else:
                title_html = h(title)
            return f"""
<article class="reader-compact-row">
  <span class="reader-dot" aria-hidden="true"></span>
  <h3>{title_html}</h3>
  <div class="reader-row-tools"><span class="reader-row-time">{h(item_display_time(item, 'published_at', 'captured_at', 'dismissed_at'))}</span>{restore_form(item) if archived else ''}</div>
</article>
"""

        def source_card(item: dict, can_open: bool = True, archived: bool = False) -> str:
            image = item_image_url(item)
            css_class = track_class(item.get("track", source.get("track", "unclassified")))
            thumb = (
                f"<div class='reader-thumb'><img src='{h(image)}' alt=''></div>"
                if image
                else f"<div class='reader-thumb reader-thumb--{h(css_class)}'><span>{h(track_meta(item.get('track', source.get('track', 'unclassified')))['short'])}</span></div>"
            )
            kind = item_display_kind(item)
            item_url = clean_text(item.get("url"))
            title = item_display_title(item)
            if archived and item_url:
                title_html = f'<a href="{h(item_url)}" target="_blank" rel="noreferrer">{h(title)}</a>'
            elif can_open:
                title_html = f'<a href="{h(item_detail_href(item))}">{h(title)}</a>'
            else:
                title_html = h(title)
            return f"""
<article class="card reader-card">
  {thumb}
  <div class="reader-body">
    <div>
      {badge(track_meta(item.get("track", source.get("track", "unclassified")))["short"], css_class)}
      {badge(status_label(item.get("status", "")), "neutral")}
      {badge(content_kind_label(kind), "neutral") if not archived else badge("不收紀錄", "suggest-skip")}
    </div>
    <h3>{title_html}</h3>
    <p class="muted break-anywhere">{h(item_display_time(item, 'published_at', 'captured_at', 'dismissed_at'))}</p>
    <p class="zh-summary">{h(source_summary(item, archived, 260))}</p>
    {f'<div class="button-row reader-card-actions" aria-label="文章操作"><a class="button reader-action-button" href="{h(item_detail_href(item))}" aria-label="閱讀 / 記錄" title="閱讀 / 記錄">{icon_span("read", "O", "icon reader-action-icon")}{action_label("閱讀 / 記錄")}</a><a class="button secondary reader-action-button" href="{h(item_url)}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{icon_span("external", "L", "icon reader-action-icon")}{action_label("原始連結")}</a></div>' if can_open and item_url else ''}
    {f'<div class="source-action-row">{restore_form(item)}</div>' if archived else ''}
  </div>
</article>
"""

        featured = sort_items([item for item in items if item_display_kind(item) in {"featured-article", "opinion-article"}])
        small_news = sort_items([item for item in items if item_display_kind(item) == "small-news" and item.get("status") != "inbox"])
        inbox = sort_items([item for item in items if item.get("status") == "inbox"])
        pending = sort_items(candidates)
        other_items = sort_items([item for item in items if item not in featured and item not in small_news and item not in inbox])
        rejected_records = sort_items([*rejected, *dismissed])

        def section(
            section_id: str,
            title: str,
            description: str,
            records: list[dict],
            empty: str,
            default_layout: str = "list",
            can_open: bool = True,
            archived: bool = False,
        ) -> str:
            cards_html = "".join(source_card(item, can_open=can_open, archived=archived) for item in records)
            list_html = "".join(source_list_row(item, can_open=can_open, archived=archived) for item in records)
            compact_html = "".join(source_compact_row(item, can_open=can_open, archived=archived) for item in records)
            empty_html = f'<div class="card"><p class="muted">{h(empty)}</p></div>'
            return f"""
<section class="reader-layout-section" id="{h(section_id)}" data-layout="{h(default_layout)}">
  <div class="layout-bar">
    <div>
      <h2>{h(title)}</h2>
      <p class="muted">{h(description)}</p>
    </div>
    {layout_toggle(section_id, default_layout)}
  </div>
  <div class="reader-grid">{cards_html or empty_html}</div>
  <div class="reader-list">{list_html or empty_html}</div>
  <div class="reader-compact-list">{compact_html or empty_html}</div>
</section>
"""

        feed_url = clean_text(source.get("feed_url"))
        site_url = clean_text(source.get("site_url"))
        css_class = track_class(source.get("track", "unclassified"))
        notice = ""
        saved = form_value(query, "saved")
        error = form_value(query, "error")
        if saved == "restored":
            notice = '<div class="notice">已重新收錄，項目會回到 RSS 待整理。</div>'
        elif saved == "source_fetch":
            notice = f'<div class="notice">已手動更新這個 RSS。{h(source_fetch_summary_from_query(query))}新的項目會進 RSS 待整理。</div>'
        elif saved == "source_keywords":
            notice = '<div class="notice">來源已儲存，並已依單一 RSS 關鍵字重盤點與重新抓取。</div>'
        elif error == "source_fetch":
            notice = f'<div class="notice">手動更新沒有成功。{h(source_fetch_summary_from_query(query))}請檢查健康狀態或 feed URL。</div>'
        body = f"""
<h1>{h(source.get("name") or "未命名來源")}</h1>
{notice}
<p class="lede">這裡先看同一個 RSS / 來源底下已收、待整理與不收的內容；要調整抓取頻率、健康狀態或關鍵字，再進編輯頁。</p>
<section class="card track-card track-card--{h(css_class)}">
  <div>
    {badge(track_meta(source.get("track", "unclassified"))["short"], css_class)}
    {badge(source_type_label(source.get("source_type", "manual")), source.get("source_type", "manual").replace("_", "-"))}
  {badge(source_status_label(source.get("status", "")), clean_text(source.get("status", "neutral")).replace("_", "-"))}
    {source_health_badge(health)}
  </div>
  <div class="metric-row">
    {metric_tile(len(featured), "精選 / 觀點", "#source-featured", "看區塊")}
    {metric_tile(len(small_news), "小消息", "#source-small-news", "看區塊")}
    {metric_tile(len(inbox) + len(pending), "待整理", "#source-inbox", "看區塊")}
    {metric_tile(len(rejected_records), "不收紀錄", "#source-rejected", "看區塊")}
  </div>
  <p class="help">抓取頻率：{h(source_frequency_label(source.get('fetch_frequency', 'daily')))}；健康狀態：{h(health.get('reason'))}</p>
  <p class="muted break-anywhere">{f'Feed：<code>{h(feed_url)}</code><br>' if feed_url else ''}{f'網站：<a href="{h(site_url)}" target="_blank" rel="noreferrer">{h(site_url)}</a>' if site_url else ''}</p>
  <div class="button-row">
    <a class="button secondary" href="/sources/edit?id={quote(source_id)}">編輯 RSS</a>
    <form method="post" action="/sources/fetch" data-source-fetch-form>
      <input type="hidden" name="id" value="{h(source_id)}">
      <input type="hidden" name="redirect" value="/sources/view?id={h(quote(source_id))}">
      <button type="submit" class="secondary">手動更新 RSS</button>
    </form>
    <a class="button quiet" href="/sources?track={quote(source.get('track', 'unclassified'))}">回 RSS 來源</a>
  </div>
</section>
{section("source-featured", "精選文章與觀點文章", "已確認值得細讀、可能後續撰稿或觀點整理的內容。", featured, "這個來源目前沒有精選文章或觀點文章。", "card")}
{section("source-small-news", "純新聞 / 小消息", "可以快速掃過、查核後短訊處理的內容。", small_news, "這個來源目前沒有小消息。", "list")}
{section("source-inbox", "待整理 / RSS 新進", "還沒完成收或不收判斷的內容，包含已入庫 inbox 和 RSS 新進。", [*inbox, *pending], "這個來源目前沒有待整理項目。", "list")}
{section("source-other", "其他已收項目", "已收但尚未歸入精選、觀點或小消息的內容。", other_items, "這個來源目前沒有其他已收項目。", "list")}
{section("source-rejected", "不收紀錄", "已被標記不收或從 RSS 待整理移出的內容，方便判斷這個 RSS 是否該調整或暫停。", rejected_records, "這個來源目前沒有不收紀錄。", "compact", can_open=False, archived=True)}
"""
        self.send_html(str(source.get("name") or "來源內容"), body)

    def show_source_edit(self, query: dict[str, list[str]]) -> None:
        source_id = (query.get("id") or [""])[0]
        source = next((row for row in load_jsonl(SOURCES) if row.get("id") == source_id), None)
        if not source:
            self.send_html("找不到來源", "<h1>找不到來源</h1>", HTTPStatus.NOT_FOUND)
            return
        self.show_source_form(source)

    def show_source_form(self, source: dict) -> None:
        source_id = source.get("id", "")
        title = "編輯來源" if source_id else "新增 RSS 來源"
        current_track = source.get("track", "digital-humanities-local-knowledge")
        if current_track not in TRACK_META:
            current_track = "digital-humanities-local-knowledge"
        current_type = source.get("source_type", "rss")
        current_status = source.get("status", "active")
        current_frequency = source.get("fetch_frequency", "daily")
        health_card = ""
        if source_id:
            health = source_health_summary(
                source,
                load_jsonl(ITEMS),
                load_jsonl(REJECTED_ITEMS),
                load_jsonl(CANDIDATES),
                load_jsonl(DISMISSED),
            )
            rss_health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
            health_card = f"""
<section class="card">
  <h2>健康狀態</h2>
  <p>{source_health_badge(health)}</p>
  <p class="muted">{h(health.get('reason'))}</p>
  <div class="metric-row">
    {metric_tile(health.get('accepted', 0), "已收下", f"/sources/view?id={quote(source_id)}#source-featured", "看已收")}
    {metric_tile(health.get('inbox', 0) + health.get('candidates', 0), "待整理", f"/sources/view?id={quote(source_id)}#source-inbox", "看待整理")}
    {metric_tile(health.get('rejected', 0), "不收 / 刪除", f"/sources/view?id={quote(source_id)}#source-rejected", "看不收")}
    {metric_tile(health.get('duplicate_skips', 0), "近次重複略過")}
  </div>
  <p class="help">最近檢查：{h(health.get('last_checked_at') or '尚未記錄')}；最近資料：{h(health.get('last_seen') or '尚未記錄')}；最近抓取狀態：{h(rss_health.get('last_fetch_status') or '尚未記錄')}。</p>
</section>
"""
        body = f"""
<h1>{h(title)}</h1>
<p class="lede">用在你想長期追蹤一個網站、Google 快訊、YouTube 頻道或 Podcast 時。RSS / Google 快訊 / YouTube / Podcast 會被每天的抓取流程處理。</p>
{health_card}
<form class="form-panel" method="post" action="/sources" data-url-preview-form data-preview-kind="source">
  <input type="hidden" name="id" value="{h(source_id)}">
  <label>主線</label>
  <select name="track" data-preview-track>{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定來源會出現在開放科技、人文與在地知識，或未分類清單。</p>
  <label>名稱</label>
  <input name="name" value="{h(source.get('name', ''))}" required data-preview-title>
  <p class="help">填你看得懂的短名稱，例如網站名、作者名或頻道名。</p>
  <label>來源群組</label>
  <input name="source_group" value="{h(source.get('source_group', 'Manual RSS'))}">
  <p class="help">把同一批來源放在一起，例如「OpenTech RSS」「縣市政府文化局」。來源列表會用這個分組。</p>
  <label>來源類型</label>
  <select name="source_type" data-preview-source-type>{source_type_options(current_type)}</select>
  <p class="help">{h(SOURCE_TYPE_HELP.get(current_type, "RSS / Google 快訊 / YouTube / Podcast 會被自動抓；其他類型目前用來保留脈絡。"))}</p>
  <label>狀態</label>
  <select name="status">{source_status_options(current_status)}</select>
  <p class="help">啟用會進入每日抓取；暫停會保留但不抓；封存代表這個來源暫時不再顯示。</p>
  <label>抓取頻率</label>
  <select name="fetch_frequency">{source_frequency_options(current_frequency)}</select>
  <p class="help">每天的流程會看這個欄位；每週與每月會參考最近一次成功抓取時間，暫停抓取則保留來源但不抓。</p>
  <label>Feed URL</label>
  <input name="feed_url" value="{h(source.get('feed_url', ''))}" placeholder="https://example.com/feed.xml" data-preview-url data-preview-feed-url>
  <p class="help">RSS / Google 快訊 / YouTube / Podcast 請填這欄。Facebook、舊 Inoreader monitor 或既有表格來源可以留空作為紀錄。</p>
  <label>Site URL</label>
  <input name="site_url" value="{h(source.get('site_url', ''))}" placeholder="https://example.com/" data-preview-site-url>
  <p class="help">原始網站首頁，方便之後回去確認來源脈絡。</p>
  <div class="preview-panel" data-preview-panel hidden>
    <div class="preview-status" data-preview-status>等待網址。</div>
    <div class="preview-result" data-preview-result></div>
  </div>
  <button type="button" class="secondary" data-preview-button>{button_content("抓取來源資訊", "rss", "R")}</button>
  <label>必須包含的關鍵字</label>
  <textarea name="required_keywords" placeholder="一行一個；留空代表不限制">{h(source_keywords_text(source, 'required_keywords'))}</textarea>
  <p class="help">若有填，RSS 單篇標題、摘要、標籤、來源或網址至少要命中其中一個才會進待整理；編輯後存檔會重盤點這個來源的待整理項目並重新抓一次。</p>
  <label>不能包含的關鍵字</label>
  <textarea name="excluded_keywords" placeholder="一行一個；留空代表不限制">{h(source_keywords_text(source, 'excluded_keywords'))}</textarea>
  <p class="help">命中這裡的單篇會在 RSS 抓取階段直接略過；若是既有待整理或候選，存檔重盤點時會以「{h(SOURCE_KEYWORD_EXCLUSION_REASON)}」移到不收紀錄。</p>
  <label>備註</label>
  <textarea name="notes">{h(source.get('notes', ''))}</textarea>
  <p class="help">可以寫為什麼要追、頻率如何、是不是從 Inoreader 舊流程轉來。</p>
  <button type="submit">儲存這個來源</button>
  <p class="help">送出後會寫進 database/sources.jsonl。要抓新資料，可以在來源列表或來源頁按「更新」。</p>
</form>
"""
        self.send_html(title, body)

    def save_source(self, data: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        existing_id = form_value(data, "id")
        existing_source = next((source for source in sources if source.get("id") == existing_id), {}) if existing_id else {}
        record = {
            "id": existing_id or stable_id("src", form_value(data, "source_group"), form_value(data, "name"), form_value(data, "feed_url")),
            "track": form_value(data, "track", "unclassified"),
            "name": form_value(data, "name"),
            "source_group": form_value(data, "source_group", "Manual RSS"),
            "source_type": form_value(data, "source_type", "rss"),
            "fetch_frequency": form_value(data, "fetch_frequency", "daily"),
            "feed_url": form_value(data, "feed_url"),
            "site_url": form_value(data, "site_url"),
            "status": form_value(data, "status", "active"),
            "required_keywords": form_lines(form_value(data, "required_keywords")),
            "excluded_keywords": form_lines(form_value(data, "excluded_keywords")),
            "notes": form_value(data, "notes"),
        }
        keywords_changed = bool(existing_id) and source_keyword_signature(existing_source) != source_keyword_signature(record)
        for preserved_key in ["rss_health", "health_assessment", "last_fetched_at"]:
            if preserved_key in existing_source:
                record[preserved_key] = existing_source[preserved_key]
        if existing_id:
            sources = [record if source.get("id") == existing_id else source for source in sources]
        else:
            if record["feed_url"] and any(source.get("feed_url") == record["feed_url"] for source in sources):
                self.send_html("已存在", f"<h1>這個 RSS 已存在</h1><p>{h(record['feed_url'])}</p><p><a href='/sources'>回來源列表</a></p>")
                return
            sources.append(record)
        sources.sort(key=lambda row: (row.get("source_group", ""), row.get("name", ""), row.get("id", "")))
        write_jsonl(SOURCES, sources)
        if keywords_changed:
            stats = self.rescan_source_keyword_exclusions(record)
            fetch_ok, _output = self.run_source_fetch(record["id"])
            query = urlencode(
                {
                    "id": record["id"],
                    "saved": "source_keywords" if fetch_ok else "source_keywords",
                    "excluded_items": str(stats.get("items", 0)),
                    "excluded_candidates": str(stats.get("candidates", 0)),
                    "fetch": "ok" if fetch_ok else "failed",
                }
            )
            self.redirect(f"/sources/view?{query}")
            return
        self.redirect(f"/sources?track={quote(record['track'])}")

    def run_command(self, data: dict[str, list[str]]) -> None:
        command_name = form_value(data, "command")
        wants_json = self.is_async_request() or form_value(data, "format") == "json"
        config = COMMANDS.get(command_name)
        if not config:
            if wants_json:
                self.send_json({"ok": False, "error": "不允許的指令"}, HTTPStatus.BAD_REQUEST)
                return
            self.send_html("不允許的指令", "<h1>不允許的指令</h1>", HTTPStatus.BAD_REQUEST)
            return
        if config.get("internal") == "commit_database_state":
            result = commit_database_state("manual")
            ok = result.get("state") in {"committed", "no-changes"}
            output = "\n".join(
                line
                for line in [
                    clean_text(result.get("message")),
                    f"commit: {clean_text(result.get('commit'))}" if result.get("commit") else "",
                    f"message: {clean_text(result.get('commit_message'))}" if result.get("commit_message") else "",
                    clean_text(result.get("output")),
                ]
                if line
            )
            if wants_json:
                self.send_json(
                    {
                        "ok": ok,
                        "label": config["label"],
                        "command": ["internal", "commit_database_state"],
                        "returncode": 0 if ok else 1,
                        "output": output or "(沒有變更需要 commit)",
                    },
                    HTTPStatus.OK,
                )
                return
            body = f"""
<h1>{h(config['label'])}</h1>
<p class="muted">狀態：{h(result.get('state'))}</p>
<pre>{h(output or '(沒有變更需要 commit)')}</pre>
<p><a href="/">回總覽</a></p>
"""
            self.send_html(str(config["label"]), body)
            return
        command = config["command"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=600)
        output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
        if wants_json:
            self.send_json(
                {
                    "ok": result.returncode == 0,
                    "label": config["label"],
                    "command": command,
                    "returncode": result.returncode,
                    "output": output,
                },
                HTTPStatus.OK,
            )
            return
        body = f"""
<h1>{h(config['label'])}</h1>
<p class="muted">Exit code: {result.returncode}</p>
<p><code>{h(' '.join(command))}</code></p>
<pre>{h(output)}</pre>
<p><a href="/">回總覽</a></p>
"""
        self.send_html(str(config["label"]), body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a local web UI for Ian Open News")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--port-scan-count", type=int, default=20, help="How many ports to try when the requested port is already in use.")
    args = parser.parse_args()

    server = None
    last_error = None
    for offset in range(max(1, args.port_scan_count)):
        port = args.port + offset
        try:
            server = ThreadingHTTPServer((args.host, port), Handler)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            last_error = exc
            continue
    if server is None:
        end_port = args.port + max(1, args.port_scan_count) - 1
        raise SystemExit(f"Ports {args.port}-{end_port} are already in use. Last error: {last_error}")

    host = server.server_address[0]
    port = server.server_address[1]
    url = f"http://{host}:{port}"
    if port != args.port:
        print(f"Port {args.port} is in use; using {port} instead.")
    print(f"Local web UI running at {url}")
    start_data_autocommit_worker()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping")


if __name__ == "__main__":
    main()
