#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import html
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse
import hashlib


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
SOURCES = DATABASE / "sources.jsonl"
ITEMS = DATABASE / "items.jsonl"

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
SOURCE_TYPES = ["rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor", "spreadsheet", "manual"]
SOURCE_STATUSES = ["active", "paused", "archived"]
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

COMMANDS = {
    "fetch_rss": {
        "label": "立刻抓 RSS",
        "description": "去啟用中的 RSS / Google 快訊 / YouTube / Podcast 來源看有沒有新內容，新增到待整理清單。",
        "button": "現在抓新資料",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "fetch_rss.py"),
            "--report",
            str(ROOT / ".cache" / "rss-fetch-report.md"),
        ],
    },
    "validate": {
        "label": "驗證資料庫",
        "description": "檢查 JSONL 欄位、主線分類、來源關聯是否正確。送 PR 前先按這個。",
        "button": "檢查資料有沒有壞",
        "command": [sys.executable, str(ROOT / "scripts" / "validate_database.py")],
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


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


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


def is_fetchable_source(source: dict) -> bool:
    return (
        source.get("status") == "active"
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


def badge(label: str, class_name: str = "neutral") -> str:
    return f'<span class="badge badge--{h(class_name)}">{h(label)}</span>'


def command_card(name: str, config: dict) -> str:
    return (
        "<div class='card command-card'>"
        f"<strong>{h(config['label'])}</strong>"
        f"<p class='muted'>{h(config['description'])}</p>"
        "<form method='post' action='/commands/run'>"
        f"<input type='hidden' name='command' value='{h(name)}'>"
        f"<button type='submit' class='secondary'>{h(config['button'])}</button>"
        "</form>"
        "</div>"
    )


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
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    nav a {{
      color: var(--ocf-dark);
      text-decoration: none;
      font-weight: 750;
      padding: 7px 10px;
      border-radius: 6px;
    }}
    nav a:hover {{ background: var(--soft); }}
    h1 {{ font-size: 28px; margin: 0 0 12px; }}
    h2 {{ font-size: 20px; margin: 30px 0 12px; }}
    h3 {{ font-size: 16px; margin: 0 0 8px; }}
    p {{ margin: 8px 0; }}
    a, code, .url-cell, .url, .break-anywhere {{ overflow-wrap: anywhere; word-break: break-word; }}
    .brand {{ font-weight: 850; color: var(--ocf-primary); }}
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
    .metric {{
      font-size: 27px;
      font-weight: 850;
      color: var(--track-color, var(--accent));
      line-height: 1.1;
    }}
    .metric-label {{ color: var(--muted); font-size: 13px; }}
    .muted {{ color: var(--muted); }}
    .help {{ color: var(--muted); font-size: 14px; margin-top: 4px; }}
    form {{ margin: 0; }}
    .form-panel, .filter-panel {{ padding: 18px; }}
    .form-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
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
    }}
    .button-row {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-start; }}
    .button-row .button, .button-row button {{ margin-top: 0; }}
    .button-opentech {{ background: var(--ocf-primary); }}
    .button-humanities {{ background: var(--humanities); }}
    .secondary {{ background: var(--ocf-cyan); }}
    .quiet {{ background: var(--ocf-dark); }}
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
    .command-card form {{ margin-top: 8px; }}
    .command-output {{ margin-top: 16px; }}
    @media (max-width: 760px) {{
      header {{ align-items: flex-start; padding: 14px 18px; }}
      main {{ padding: 20px 16px; }}
      .two-column {{ grid-template-columns: 1fr; }}
      .metric-row {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <header>
    <strong class="brand">Ian Open News</strong>
    <nav>
      <a href="/">共通入口</a>
      <a href="/track/open-tech-open-industry">開放科技</a>
      <a href="/track/digital-humanities-local-knowledge">人文知識</a>
      <a href="/sources">RSS 來源</a>
      <a href="/items/new">加收藏</a>
      <a href="/sources/new">加 RSS</a>
    </nav>
  </header>
  <main>{body}</main>
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

    def redirect(self, path: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", path)
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
        elif parsed.path.startswith("/track/"):
            self.show_track(parsed.path.removeprefix("/track/"))
        elif parsed.path == "/items/new":
            self.show_item_form(query)
        elif parsed.path == "/sources":
            self.show_sources(query)
        elif parsed.path == "/sources/new":
            self.show_source_form({"track": (query.get("track") or ["digital-humanities-local-knowledge"])[0]})
        elif parsed.path == "/sources/edit":
            self.show_source_edit(query)
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/items":
            self.save_item(self.read_form())
        elif parsed.path == "/sources":
            self.save_source(self.read_form())
        elif parsed.path == "/commands/run":
            self.run_command(self.read_form())
        else:
            self.send_html("找不到", "<h1>找不到頁面</h1>", HTTPStatus.NOT_FOUND)

    def show_home(self, query: dict[str, list[str]]) -> None:
        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        notice = ""
        if query.get("saved"):
            notice = '<div class="notice">已儲存。</div>'
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
            inbox_items = count_items(items, track, "inbox")
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
      <div><div class="metric">{total_items}</div><div class="metric-label">全部項目</div></div>
      <div><div class="metric">{inbox_items}</div><div class="metric-label">待整理</div></div>
      <div><div class="metric">{source_count}</div><div class="metric-label">來源</div></div>
      <div><div class="metric">{fetchable_count}</div><div class="metric-label">會自動抓</div></div>
    </div>
    <div class="button-row">
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
    <h3>新增 RSS 來源</h3>
    <p class="muted">看到值得長期追蹤的網站、Google 快訊、YouTube 或 Podcast，就先加到來源資料庫。</p>
    <p><a class="button secondary" href="/sources/new">新增一個 RSS</a></p>
    <p class="help">新增後每天 10:00、18:00 的流程才會有機會抓到它。</p>
  </div>
  <div class="card">
    <h3>全部 RSS 來源</h3>
    <p class="muted">依主線、來源類型、來源群組查看目前追蹤中的網站，也可以進去編輯或暫停。</p>
    <p><a class="button quiet" href="/sources">打開來源列表</a></p>
    <p class="help">長網址會自動換行，不會把表格撐爆。</p>
  </div>
</div>
<h2>本機指令</h2>
<p class="lede">這些按鈕只會執行固定 allowlist 指令；每顆按鈕下方都有白話說明，方便你不用記終端機命令。</p>
<div class="grid">{''.join(command_cards)}</div>
"""
        self.send_html("總覽", body)

    def show_track(self, track: str) -> None:
        if track not in TRACK_META:
            self.send_html("找不到主線", "<h1>找不到這條知識主線</h1>", HTTPStatus.NOT_FOUND)
            return

        items = load_jsonl(ITEMS)
        sources = load_jsonl(SOURCES)
        meta = track_meta(track)
        css_class = track_class(track)
        button_class = f"button-{css_class}" if css_class in {"opentech", "humanities"} else "secondary"
        track_items = [item for item in items if item.get("track") == track]
        inbox_items = [item for item in track_items if item.get("status") == "inbox"]
        track_sources = [source for source in sources if source.get("track") == track and source.get("status") != "archived"]
        fetchable_sources = [source for source in track_sources if is_fetchable_source(source)]
        source_types = Counter(source.get("source_type", "manual") for source in track_sources)
        source_groups = Counter(source.get("source_group", "未標示群組") for source in track_sources)
        recent_items = sorted(
            inbox_items,
            key=lambda item: (item.get("captured_at", ""), item.get("published_at", ""), item.get("title", "")),
            reverse=True,
        )[:12]

        item_rows = []
        for item in recent_items:
            title = item.get("title") or item.get("url") or "未命名項目"
            source_name = item.get("source_name") or item.get("author") or "未標示來源"
            captured = item.get("captured_at") or item.get("published_at") or "未標示日期"
            item_rows.append(
                f"""
<div class="list-item list-item--{h(css_class)}">
  <strong><a href="{h(item.get('url'))}" target="_blank" rel="noreferrer">{h(title)}</a></strong>
  <p class="muted">{h(source_name)} · {h(captured)}</p>
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
    <div><div class="metric">{len(track_items)}</div><div class="metric-label">全部項目</div></div>
    <div><div class="metric">{len(inbox_items)}</div><div class="metric-label">待整理</div></div>
    <div><div class="metric">{len(track_sources)}</div><div class="metric-label">來源</div></div>
    <div><div class="metric">{len(fetchable_sources)}</div><div class="metric-label">會自動抓</div></div>
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
<p class="lede">用在你看到一篇文章、一個頁面或一個案例，想先丟進待整理清單時。這裡新增的是單筆知識項目，不是長期 RSS 來源。</p>
<form class="form-panel" method="post" action="/items">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定它會出現在「開放科技」或「人文與在地知識」哪一個工作台。</p>
  <label>標題</label>
  <input name="title" value="{h(title)}" required>
  <p class="help">通常用原本網頁標題就好，之後審稿時再改成更清楚的標題。</p>
  <label>網址</label>
  <input name="url" value="{h(url)}" required>
  <p class="help">網址很長也沒關係，列表會自動換行。</p>
  <label>來源 / 網站 / 作者</label>
  <input name="source_name" placeholder="例如：報導者、Open Knowledge Foundation">
  <p class="help">不知道作者時，先填網站或組織名稱。</p>
  <label>發布日期</label>
  <input name="published_at" placeholder="YYYY-MM-DD">
  <p class="help">不確定可以留空，之後整理時再補。</p>
  <label>摘要或摘記</label>
  <textarea name="summary"></textarea>
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
        url = form_value(data, "url")
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
                    "feed_url": "",
                    "site_url": "",
                    "status": "active",
                    "notes": "由本機網頁加入。",
                },
            )
        tags = [tag.strip() for tag in form_value(data, "tags").split(",") if tag.strip()]
        notes = form_value(data, "notes")
        append_jsonl(
            ITEMS,
            {
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
                "captured_at": datetime.now(timezone.utc).date().isoformat(),
                "summary": form_value(data, "summary"),
                "tags": tags,
                "origin": "manual-web",
                "reference": {"created_by": "local_web"},
                "review": default_review(notes),
            },
        )
        self.redirect("/?saved=item")

    def show_sources(self, query: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
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
                    feed_url = source.get("feed_url") or ""
                    site_url = source.get("site_url") or ""
                    type_class = source_type.replace("_", "-")
                    status_class = status.replace("_", "-")
                    site_link = ""
                    if site_url:
                        site_link = f'<br><a class="muted break-anywhere" href="{h(site_url)}" target="_blank" rel="noreferrer">{h(site_url)}</a>'
                    feed_display = '<span class="muted">沒有 feed URL</span>'
                    if feed_url:
                        feed_display = f'<code class="url">{h(feed_url)}</code>'
                    rows.append(
                        "<tr>"
                        f"<td><strong>{h(source.get('name'))}</strong>"
                        f"{site_link}</td>"
                        f"<td>{badge(source_type_label(source_type), type_class)}</td>"
                        f"<td>{badge(source_status_label(status), status_class)}</td>"
                        f"<td class='url-cell'>{feed_display}</td>"
                        f"<td><a href='/sources/edit?id={quote(source.get('id', ''))}'>編輯</a></td>"
                        "</tr>"
                    )
                source_sections.append(
                    f"""
<details class="source-group" open>
  <summary>{h(group)} <span class="muted">({len(group_sources)})</span></summary>
  <table>
    <thead><tr><th>名稱</th><th>類型</th><th>狀態</th><th>Feed URL</th><th></th></tr></thead>
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
    <div><div class="metric">{track_counts.get(track, 0)}</div><div class="metric-label">來源</div></div>
    <div><div class="metric">{fetch_counts.get(track, 0)}</div><div class="metric-label">會自動抓</div></div>
  </div>
  <p class="help">會自動抓代表狀態是啟用，且類型是 RSS、Google 快訊、YouTube 或 Podcast。</p>
</div>
"""
            )
        body = f"""
<h1>RSS 來源分類</h1>
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
        body = f"""
<h1>{h(title)}</h1>
<p class="lede">用在你想長期追蹤一個網站、Google 快訊、YouTube 頻道或 Podcast 時。RSS / Google 快訊 / YouTube / Podcast 會被每天的抓取流程處理。</p>
<form class="form-panel" method="post" action="/sources">
  <input type="hidden" name="id" value="{h(source_id)}">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, current_track)}</select>
  <p class="help">這決定來源會出現在開放科技、人文與在地知識，或未分類清單。</p>
  <label>名稱</label>
  <input name="name" value="{h(source.get('name', ''))}" required>
  <p class="help">填你看得懂的短名稱，例如網站名、作者名或頻道名。</p>
  <label>來源群組</label>
  <input name="source_group" value="{h(source.get('source_group', 'Manual RSS'))}">
  <p class="help">把同一批來源放在一起，例如「OpenTech RSS」「縣市政府文化局」。來源列表會用這個分組。</p>
  <label>來源類型</label>
  <select name="source_type">{source_type_options(current_type)}</select>
  <p class="help">{h(SOURCE_TYPE_HELP.get(current_type, "RSS / Google 快訊 / YouTube / Podcast 會被自動抓；其他類型目前用來保留脈絡。"))}</p>
  <label>狀態</label>
  <select name="status">{source_status_options(current_status)}</select>
  <p class="help">啟用會進入每日抓取；暫停會保留但不抓；封存代表這個來源暫時不再顯示。</p>
  <label>Feed URL</label>
  <input name="feed_url" value="{h(source.get('feed_url', ''))}" placeholder="https://example.com/feed.xml">
  <p class="help">RSS / Google 快訊 / YouTube / Podcast 請填這欄。Facebook、舊 Inoreader monitor 或既有表格來源可以留空作為紀錄。</p>
  <label>Site URL</label>
  <input name="site_url" value="{h(source.get('site_url', ''))}" placeholder="https://example.com/">
  <p class="help">原始網站首頁，方便之後回去確認來源脈絡。</p>
  <label>備註</label>
  <textarea name="notes">{h(source.get('notes', ''))}</textarea>
  <p class="help">可以寫為什麼要追、頻率如何、是不是從 Inoreader 舊流程轉來。</p>
  <button type="submit">儲存這個來源</button>
  <p class="help">送出後會寫進 database/sources.jsonl。要真的抓新資料，可以回首頁按「現在抓新資料」。</p>
</form>
"""
        self.send_html(title, body)

    def save_source(self, data: dict[str, list[str]]) -> None:
        sources = load_jsonl(SOURCES)
        existing_id = form_value(data, "id")
        record = {
            "id": existing_id or stable_id("src", form_value(data, "source_group"), form_value(data, "name"), form_value(data, "feed_url")),
            "track": form_value(data, "track", "unclassified"),
            "name": form_value(data, "name"),
            "source_group": form_value(data, "source_group", "Manual RSS"),
            "source_type": form_value(data, "source_type", "rss"),
            "feed_url": form_value(data, "feed_url"),
            "site_url": form_value(data, "site_url"),
            "status": form_value(data, "status", "active"),
            "notes": form_value(data, "notes"),
        }
        if existing_id:
            sources = [record if source.get("id") == existing_id else source for source in sources]
        else:
            if record["feed_url"] and any(source.get("feed_url") == record["feed_url"] for source in sources):
                self.send_html("已存在", f"<h1>這個 RSS 已存在</h1><p>{h(record['feed_url'])}</p><p><a href='/sources'>回來源列表</a></p>")
                return
            sources.append(record)
        sources.sort(key=lambda row: (row.get("source_group", ""), row.get("name", ""), row.get("id", "")))
        write_jsonl(SOURCES, sources)
        self.redirect(f"/sources?track={quote(record['track'])}")

    def run_command(self, data: dict[str, list[str]]) -> None:
        command_name = form_value(data, "command")
        config = COMMANDS.get(command_name)
        if not config:
            self.send_html("不允許的指令", "<h1>不允許的指令</h1>", HTTPStatus.BAD_REQUEST)
            return
        command = config["command"]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=600)
        output = result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else "")
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping")


if __name__ == "__main__":
    main()
