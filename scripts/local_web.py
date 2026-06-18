#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import html
import json
import re
import subprocess
import sys
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
SOURCE_TYPES = ["rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor", "manual"]
SOURCE_STATUSES = ["active", "paused", "archived"]

COMMANDS = {
    "fetch_rss": {
        "label": "抓 RSS",
        "description": "執行 scripts/fetch_rss.py，新增近幾天的 inbox items。",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "fetch_rss.py"),
            "--report",
            str(ROOT / ".cache" / "rss-fetch-report.md"),
        ],
    },
    "validate": {
        "label": "驗證資料庫",
        "description": "執行 scripts/validate_database.py，檢查 JSONL 欄位、分類與關聯。",
        "command": [sys.executable, str(ROOT / "scripts" / "validate_database.py")],
    },
    "export_sqlite": {
        "label": "匯出 SQLite",
        "description": "執行 scripts/export_sqlite.py，產生 .cache/knowledge.sqlite。",
        "command": [
            sys.executable,
            str(ROOT / "scripts" / "export_sqlite.py"),
            "--output",
            str(ROOT / ".cache" / "knowledge.sqlite"),
        ],
    },
    "git_status": {
        "label": "看 git status",
        "description": "顯示目前有哪些檔案變更。",
        "command": ["git", "status", "--short"],
    },
    "git_diff_stat": {
        "label": "看 diff stat",
        "description": "顯示目前變更的摘要統計。",
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


def page(title: str, body: str) -> bytes:
    html_doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)} - Ian Open News</title>
  <style>
    :root {{
      --bg: #f7f5ef;
      --ink: #1e252c;
      --muted: #68737d;
      --line: #d8d2c6;
      --panel: #ffffff;
      --accent: #0c766f;
      --accent-2: #8a4b10;
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
      gap: 20px;
      padding: 18px 28px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.88);
      position: sticky;
      top: 0;
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px; }}
    nav a {{ margin-left: 14px; color: var(--accent); text-decoration: none; font-weight: 650; }}
    h1 {{ font-size: 28px; margin: 0 0 18px; }}
    h2 {{ font-size: 20px; margin: 28px 0 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 14px; }}
    .card, form, table {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(0,0,0,.04);
    }}
    .card {{ padding: 18px; }}
    .metric {{ font-size: 30px; font-weight: 800; color: var(--accent); }}
    .muted {{ color: var(--muted); }}
    form {{ padding: 18px; }}
    label {{ display: block; font-weight: 700; margin: 13px 0 5px; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      background: #fff;
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
      font-weight: 750;
      text-decoration: none;
      cursor: pointer;
      margin-top: 16px;
    }}
    .secondary {{ background: var(--accent-2); }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
    th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ background: #fbfaf6; color: var(--muted); font-size: 13px; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ background: #eee8dc; padding: 2px 5px; border-radius: 4px; }}
    pre {{ white-space: pre-wrap; background: #162024; color: #eaf1ec; padding: 16px; border-radius: 8px; overflow: auto; }}
    .notice {{ border-left: 4px solid var(--accent); padding: 10px 14px; background: #eef8f5; border-radius: 6px; margin-bottom: 18px; }}
  </style>
</head>
<body>
  <header>
    <strong>Ian Open News</strong>
    <nav>
      <a href="/">總覽</a>
      <a href="/items/new">加收藏</a>
      <a href="/sources">RSS 來源</a>
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
        elif parsed.path == "/items/new":
            self.show_item_form(query)
        elif parsed.path == "/sources":
            self.show_sources(query)
        elif parsed.path == "/sources/new":
            self.show_source_form({})
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
        active_fetchable = [
            source for source in sources
            if source.get("status") == "active"
            and source.get("track") in {"digital-humanities-local-knowledge", "open-tech-open-industry"}
            and source.get("source_type") in {"rss", "google-alert", "youtube", "podcast"}
        ]
        notice = ""
        if query.get("saved"):
            notice = '<div class="notice">已儲存。</div>'
        bookmarklet = (
            "javascript:location.href='http://127.0.0.1:8765/items/new?url='"
            "+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)"
        )
        command_cards = []
        for name, config in COMMANDS.items():
            command_cards.append(
                "<div class='card'>"
                f"<strong>{h(config['label'])}</strong>"
                f"<p class='muted'>{h(config['description'])}</p>"
                "<form method='post' action='/commands/run'>"
                f"<input type='hidden' name='command' value='{h(name)}'>"
                "<button type='submit' class='secondary'>執行</button>"
                "</form>"
                "</div>"
            )
        body = f"""
<h1>知識收件箱</h1>
{notice}
<div class="grid">
  <div class="card"><div class="metric">{len(items)}</div><div class="muted">知識項目</div></div>
  <div class="card"><div class="metric">{len(sources)}</div><div class="muted">來源</div></div>
  <div class="card"><div class="metric">{len(active_fetchable)}</div><div class="muted">每日自動抓取來源</div></div>
</div>
<h2>快速操作</h2>
<div class="grid">
  <div class="card">
    <strong>看到好頁面</strong>
    <p class="muted">把這個 bookmarklet 加到瀏覽器書籤列，看到想收的頁面時點一下。</p>
    <p><a class="button" href="{h(bookmarklet)}">加入 Ian Open News</a></p>
  </div>
  <div class="card">
    <strong>手動抓 RSS</strong>
    <p class="muted">立刻跑一次 `scripts/fetch_rss.py`，結果會寫進 `database/items.jsonl`。</p>
    <form method="post" action="/commands/run">
      <input type="hidden" name="command" value="fetch_rss">
      <button type="submit" class="secondary">現在抓取</button>
    </form>
  </div>
</div>
<h2>本機指令</h2>
<div class="grid">{''.join(command_cards)}</div>
"""
        self.send_html("總覽", body)

    def show_item_form(self, query: dict[str, list[str]]) -> None:
        title = clean_text(unquote((query.get("title") or [""])[0]))
        url = clean_text(unquote((query.get("url") or [""])[0]))
        body = f"""
<h1>加入收藏</h1>
<form method="post" action="/items">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, "digital-humanities-local-knowledge")}</select>
  <label>標題</label>
  <input name="title" value="{h(title)}" required>
  <label>網址</label>
  <input name="url" value="{h(url)}" required>
  <label>來源 / 網站 / 作者</label>
  <input name="source_name" placeholder="例如：報導者、Open Knowledge Foundation">
  <label>發布日期</label>
  <input name="published_at" placeholder="YYYY-MM-DD">
  <label>摘要或摘記</label>
  <textarea name="summary"></textarea>
  <label>標籤</label>
  <input name="tags" placeholder="用逗號分隔">
  <label>備註 / 為什麼值得追</label>
  <textarea name="notes"></textarea>
  <button type="submit">加入 inbox</button>
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
        rows = []
        for source in sources:
            if source.get("status") == "archived":
                continue
            rows.append(
                "<tr>"
                f"<td>{h(source.get('name'))}<br><span class='muted'>{h(source.get('source_group'))}</span></td>"
                f"<td>{h(source.get('track'))}</td>"
                f"<td>{h(source.get('source_type'))}</td>"
                f"<td>{h(source.get('status'))}</td>"
                f"<td><code>{h(source.get('feed_url'))}</code></td>"
                f"<td><a href='/sources/edit?id={quote(source.get('id', ''))}'>編輯</a></td>"
                "</tr>"
            )
        body = f"""
<h1>RSS 來源</h1>
<p><a class="button" href="/sources/new">新增 RSS</a></p>
<table>
  <thead><tr><th>名稱</th><th>主線</th><th>類型</th><th>狀態</th><th>Feed URL</th><th></th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>
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
        title = "編輯 RSS" if source_id else "新增 RSS"
        body = f"""
<h1>{h(title)}</h1>
<form method="post" action="/sources">
  <input type="hidden" name="id" value="{h(source_id)}">
  <label>主線</label>
  <select name="track">{option_list(TRACKS, source.get("track", "digital-humanities-local-knowledge"))}</select>
  <label>名稱</label>
  <input name="name" value="{h(source.get('name', ''))}" required>
  <label>來源群組</label>
  <input name="source_group" value="{h(source.get('source_group', 'Manual RSS'))}">
  <label>Source type</label>
  <select name="source_type">{option_list(SOURCE_TYPES, source.get("source_type", "rss"))}</select>
  <label>Status</label>
  <select name="status">{option_list(SOURCE_STATUSES, source.get("status", "active"))}</select>
  <label>Feed URL</label>
  <input name="feed_url" value="{h(source.get('feed_url', ''))}" placeholder="https://example.com/feed.xml" required>
  <label>Site URL</label>
  <input name="site_url" value="{h(source.get('site_url', ''))}" placeholder="https://example.com/">
  <label>備註</label>
  <textarea name="notes">{h(source.get('notes', ''))}</textarea>
  <button type="submit">儲存來源</button>
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
            if any(source.get("feed_url") == record["feed_url"] for source in sources):
                self.send_html("已存在", f"<h1>這個 RSS 已存在</h1><p>{h(record['feed_url'])}</p><p><a href='/sources'>回來源列表</a></p>")
                return
            sources.append(record)
        sources.sort(key=lambda row: (row.get("source_group", ""), row.get("name", ""), row.get("id", "")))
        write_jsonl(SOURCES, sources)
        self.redirect("/sources")

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
