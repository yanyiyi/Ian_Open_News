#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from local_web import (
    ITEMS,
    action_icon,
    action_label,
    clean_text,
    content_kind_label,
    h,
    item_current_reading_age_days,
    item_display_time,
    item_display_title,
    item_is_current_reading,
    is_reader_item,
    item_display_kind,
    item_image_url,
    item_sort_time,
    item_visible_tags,
    item_zh_summary,
    load_jsonl,
    markdown_to_html,
    track_meta,
)
from page_metadata import text_to_markdown


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "reader" / "index.html"
PUBLIC_KINDS = {"featured-article", "small-news", "opinion-article"}
PRIMARY_KINDS = {"featured-article", "opinion-article"}
TIME_FILTER_OPTIONS = [
    ("three-days", "這三天（-3 天）"),
    ("week", "這一週"),
    ("month", "這一個月（-30 天）"),
    ("quarter", "這一季"),
    ("year", "這一年"),
    ("custom", "自定時間範圍"),
    ("all", "全部"),
]


def repo_web_url() -> str:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "https://github.com/yanyiyi/Ian_Open_News"
    remote = result.stdout.strip()
    if remote.startswith("git@github.com:"):
        return "https://github.com/" + remote.removeprefix("git@github.com:").removesuffix(".git")
    if remote.startswith("https://github.com/"):
        return remote.removesuffix(".git")
    return "https://github.com/yanyiyi/Ian_Open_News"


def branch_name() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "main"
    return result.stdout.strip() or "main"


def article_filename(item: dict) -> str:
    item_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_text(item.get("id")) or "item").strip("-")
    return f"{item_id}.html"


def article_href(item: dict, from_article: bool = False) -> str:
    prefix = "" if from_article else "articles/"
    return prefix + article_filename(item)


def item_date(item: dict) -> str:
    return item_display_time(item, "published_at", "captured_at")


def item_data_date(item: dict) -> str:
    return item_sort_time(item)


def time_filter_controls() -> str:
    options = "\n".join(
        f'<option value="{h(value)}"{" selected" if value == "all" else ""}>{h(label)}</option>'
        for value, label in TIME_FILTER_OPTIONS
    )
    return f"""
<section class="reader-time-filter" data-time-filter>
  <div>
    <label for="reader-time-range">時間</label>
    <select id="reader-time-range" data-time-select>
      {options}
    </select>
  </div>
  <div class="reader-time-custom" data-time-custom hidden>
    <div>
      <label for="reader-time-start">開始日期</label>
      <input id="reader-time-start" type="date" data-time-start>
    </div>
    <div>
      <label for="reader-time-end">結束日期</label>
      <input id="reader-time-end" type="date" data-time-end>
    </div>
  </div>
  <p class="generated" data-time-count></p>
</section>
"""


def time_filter_script() -> str:
    return """
<script>
(() => {
  const panel = document.querySelector("[data-time-filter]");
  if (!panel) return;
  const select = panel.querySelector("[data-time-select]");
  const custom = panel.querySelector("[data-time-custom]");
  const startInput = panel.querySelector("[data-time-start]");
  const endInput = panel.querySelector("[data-time-end]");
  const count = panel.querySelector("[data-time-count]");
  const items = Array.from(document.querySelectorAll("[data-reader-item]"));
  const empty = document.querySelector("[data-time-empty]");

  function parseInputDate(input, endOfDay) {
    if (!input || !input.value) return null;
    const parts = input.value.split("-").map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return null;
    const date = new Date(parts[0], parts[1] - 1, parts[2]);
    if (endOfDay) date.setDate(date.getDate() + 1);
    return date;
  }

  function rangeBounds() {
    const now = new Date();
    let start = null;
    let end = null;
    if (select.value === "three-days") {
      start = new Date(now);
      start.setDate(start.getDate() - 3);
    } else if (select.value === "week") {
      start = new Date(now);
      start.setDate(start.getDate() - 7);
    } else if (select.value === "month") {
      start = new Date(now);
      start.setDate(start.getDate() - 30);
    } else if (select.value === "quarter") {
      start = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);
    } else if (select.value === "year") {
      start = new Date(now.getFullYear(), 0, 1);
    } else if (select.value === "custom") {
      start = parseInputDate(startInput, false);
      end = parseInputDate(endInput, true);
    }
    return { start, end };
  }

  function applyTimeFilter() {
    const isCustom = select.value === "custom";
    custom.hidden = !isCustom;
    custom.querySelectorAll("input").forEach((input) => {
      input.disabled = !isCustom;
    });
    const { start, end } = rangeBounds();
    let visible = 0;
    items.forEach((item) => {
      const raw = item.dataset.itemDate || "";
      const date = raw ? new Date(raw) : null;
      const hasDate = date && !Number.isNaN(date.getTime());
      const keep = (!start && !end) || (hasDate && (!start || date >= start) && (!end || date < end));
      item.classList.toggle("reader-hidden-by-time", !keep);
      if (keep) visible += 1;
    });
    if (count) count.textContent = `顯示 ${visible} / ${items.length} 筆`;
    if (empty) empty.hidden = visible > 0;
  }

  select.addEventListener("change", applyTimeFilter);
  [startInput, endInput].forEach((input) => {
    if (input) input.addEventListener("change", applyTimeFilter);
  });
  applyTimeFilter();
})();
</script>
"""


def reader_image_url(item: dict, depth: int = 0) -> str:
    url = item_image_url(item)
    if url.startswith("/reader/"):
        prefix = "../" if depth else ""
        return prefix + url.removeprefix("/reader/").lstrip("/")
    return url


def item_body_markdown(item: dict) -> str:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    translated = clean_text(metadata.get("translated_article_markdown_zh"))
    if translated:
        return translated
    markdown = clean_text(metadata.get("article_markdown"))
    if markdown:
        return markdown
    article_text = clean_text(metadata.get("article_text"))
    if article_text:
        return text_to_markdown(article_text, title=metadata.get("title") or item_display_title(item))
    return ""


def item_is_public_reader(item: dict) -> bool:
    if item.get("track") != "open-tech-open-industry":
        return False
    if not is_reader_item(item):
        return False
    return item_display_kind(item) in PUBLIC_KINDS


def public_reader_badges(item: dict) -> str:
    if not item_is_current_reading(item):
        return ""
    age = item_current_reading_age_days(item)
    aged = f'<span class="badge badge--reading">已標記 {h(str(age))} 天</span>' if age >= 2 else ""
    return f'<span class="badge badge--reading">Ian 近期正在讀</span><span class="badge badge--reading">想分享</span>{aged}'


def public_tag_chips(item: dict, limit: int = 6) -> str:
    tags = item_visible_tags(item, limit)
    if not tags:
        return ""
    return '<div class="tag-chip-list">' + "".join(f'<span class="tag-chip">{h(tag)}</span>' for tag in tags) + "</div>"


def kind_order(item: dict) -> tuple[int, str, str, str]:
    kind = item_display_kind(item)
    order = {"featured-article": 0, "opinion-article": 1, "small-news": 2}.get(kind, 9)
    return (order, item_sort_time(item), item_display_title(item), clean_text(item.get("id")))


def note_pr_url(item: dict, repo_url: str, branch: str) -> str:
    return f"{repo_url}/new/{branch}/reader-notes?filename={clean_text(item.get('id')) or 'item'}.md"


def page_shell(title: str, body: str, current: str = "index", depth: int = 0, include_time_filter: bool = False) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    root_prefix = "../" if depth else ""
    nav = f"""
<nav>
  <a class="{h('is-active' if current == 'index' else '')}" href="{root_prefix}index.html">精選與觀點</a>
  <a class="{h('is-active' if current == 'news' else '')}" href="{root_prefix}news.html">小消息</a>
</nav>
"""
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)} - Ian Open News</title>
  <style>
    :root {{
      --ink: #111827;
      --muted: #5b6472;
      --line: #d9deea;
      --bg: #f6f7fb;
      --panel: #ffffff;
      --accent: #6450dc;
      --cyan: #0091da;
      --magenta: #ce0058;
      --soft: #eef1fb;
      --link: #193f8f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
      line-height: 1.62;
    }}
    header {{ background: #fff; border-bottom: 1px solid var(--line); }}
    .masthead {{ max-width: 1120px; margin: 0 auto; padding: 26px 22px 18px; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 22px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 42px); letter-spacing: 0; line-height: 1.18; }}
    h2 {{ margin: 0 0 8px; font-size: 22px; letter-spacing: 0; line-height: 1.3; }}
    h3 {{ margin: 0 0 6px; letter-spacing: 0; line-height: 1.35; }}
    p {{ margin: 8px 0; }}
    a {{ color: var(--link); overflow-wrap: anywhere; text-underline-offset: 2px; }}
    a:hover {{ color: var(--accent); }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }}
    nav a, .button, button {{
      border: 0;
      border-radius: 6px;
      padding: 9px 12px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 800;
      text-decoration: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }}
    nav a:hover, .button:hover, button:hover {{ color: #fff; }}
    nav a:not(.is-active), .button.secondary {{ background: var(--cyan); }}
    .button.quiet, button.quiet {{ background: #273244; }}
    .lede {{ max-width: 820px; color: var(--muted); }}
    .generated {{ color: var(--muted); font-size: 13px; }}
    .badge {{
      border-radius: 6px;
      background: var(--soft);
      color: #273244;
      padding: 3px 7px;
      font-size: 12px;
      font-weight: 850;
      display: inline-flex;
      margin: 0 4px 4px 0;
    }}
    .badge--reading {{ background: #fff8db; color: #7a5a00; }}
    .tag-chip-list {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }}
    .tag-chip {{
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 4px 7px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: #273244;
      font-size: 12px;
      font-weight: 800;
      line-height: 1.25;
    }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; margin-top: 12px; }}
    .story-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      display: grid;
      grid-template-rows: 170px auto;
    }}
    .thumb {{
      background: linear-gradient(135deg, var(--accent), var(--cyan));
      color: #fff;
      display: flex;
      align-items: flex-end;
      padding: 12px;
      font-weight: 900;
      min-height: 170px;
    }}
    .thumb img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
    .story-body {{ padding: 14px; }}
    .summary {{ white-space: pre-wrap; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 12px; }}
    .story-card .actions {{ gap: 6px; margin-top: 8px; }}
    .story-card .actions {{ justify-content: flex-end; }}
    .story-card .actions .reader-action-button {{
      width: 30px;
      height: 30px;
      min-width: 30px;
      padding: 0;
      border-radius: 6px;
      gap: 0;
      font-size: 0;
      line-height: 1;
    }}
    .story-card .actions svg {{
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
    .news-list {{ display: grid; gap: 10px; margin-top: 12px; }}
    .news-item {{
      background: #fff;
      border: 1px solid var(--line);
      border-left: 4px solid var(--link);
      border-radius: 8px;
      padding: 16px 18px;
    }}
    .news-item h3 {{ margin: 8px 0 10px; font-size: 19px; }}
    .news-item h3 a {{ color: #4f3ed2; font-weight: 850; }}
    .news-item .summary {{ margin: 0; font-size: 16px; line-height: 1.68; }}
    .reader-time-filter {{
      display: flex;
      align-items: end;
      flex-wrap: wrap;
      gap: 10px;
      margin: 0 0 18px;
      padding: 12px 14px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .reader-time-filter label {{
      display: block;
      margin: 0 0 5px;
      font-weight: 850;
      color: var(--ink);
    }}
    .reader-time-filter select,
    .reader-time-filter input {{
      width: 100%;
      min-width: 190px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      color: var(--ink);
      background: #fff;
      font: inherit;
    }}
    .reader-time-custom {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .reader-time-custom[hidden],
    .reader-hidden-by-time {{
      display: none !important;
    }}
    .reader-time-filter .generated {{
      margin: 0 0 7px;
    }}
    .article-layout {{ display: grid; grid-template-columns: minmax(0, 760px) minmax(260px, 1fr); gap: 18px; align-items: start; }}
    .article-panel, .side-panel {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .article-body {{ max-width: 760px; }}
    .article-body img {{ max-width: 100%; height: auto; }}
    .article-body pre {{ white-space: pre-wrap; overflow: auto; background: #162024; color: #eaf1ec; padding: 12px; border-radius: 8px; }}
    .article-body blockquote {{ border-left: 4px solid var(--line); padding-left: 12px; color: var(--muted); }}
    textarea {{
      width: 100%;
      min-height: 180px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      font: inherit;
    }}
    .empty {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 18px; }}
    @media (max-width: 820px) {{
      main, .masthead {{ padding-left: 16px; padding-right: 16px; }}
      .article-layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="masthead">
      <h1>{h(title)}</h1>
      <p class="lede">Ian Open News 開放科技閱讀版。首頁優先放精選文章與觀點文章，小消息改用列表頁快速掃讀。</p>
      <p class="generated">產生時間：{h(generated_at)}</p>
      {nav}
    </div>
  </header>
  <main>{body}</main>
  {time_filter_script() if include_time_filter else ""}
</body>
</html>
"""


def item_card(item: dict) -> str:
    kind = item_display_kind(item)
    image = reader_image_url(item)
    image_html = f'<img src="{h(image)}" alt="">' if image else f"<span>{h(track_meta(item.get('track', ''))['short'])}</span>"
    summary = item_zh_summary(item, 440)
    has_body = bool(item_body_markdown(item))
    return f"""
<article class="story-card" data-reader-item data-item-date="{h(item_data_date(item))}">
  <div class="thumb">{image_html}</div>
  <div class="story-body">
    <div>
      <span class="badge">開放科技</span>
      <span class="badge">{h(content_kind_label(kind))}</span>
      {public_reader_badges(item)}
      {'<span class="badge">已載入本機全文</span>' if has_body else ''}
      <span class="badge">{h(item_date(item))}</span>
    </div>
    <h2><a href="{h(article_href(item))}">{h(item_display_title(item))}</a></h2>
    <p class="summary">{h(summary)}</p>
    {public_tag_chips(item)}
    <div class="actions">
      <a class="button secondary reader-action-button" href="{h(article_href(item))}" aria-label="閱讀單篇" title="閱讀單篇">{action_icon("read")}{action_label("閱讀單篇")}</a>
      {f'<a class="button quiet reader-action-button" href="{h(clean_text(item.get("url")))}" target="_blank" rel="noreferrer" aria-label="原始連結" title="原始連結">{action_icon("external")}{action_label("原始連結")}</a>' if clean_text(item.get("url")) else ''}
    </div>
  </div>
</article>
"""


def news_row(item: dict, depth: int = 0) -> str:
    prefix = "../" if depth else ""
    summary = item_zh_summary(item, 220)
    has_body = bool(item_body_markdown(item))
    return f"""
<article class="news-item" data-reader-item data-item-date="{h(item_data_date(item))}">
  <div>
    <span class="badge">{h(content_kind_label(item_display_kind(item)))}</span>
    {public_reader_badges(item)}
    {'<span class="badge">已載入本機全文</span>' if has_body else ''}
    <span class="badge">{h(item_date(item))}</span>
  </div>
  <h3><a href="{h(prefix + article_href(item))}">{h(item_display_title(item))}</a></h3>
  <p class="summary">{h(summary)}</p>
  {public_tag_chips(item, 5)}
</article>
"""


def edit_record_html(item: dict) -> str:
    lines = []
    local_decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
    if local_decision:
        lines.append(f"本機決定：{clean_text(local_decision.get('action'))} / {clean_text(local_decision.get('decided_at'))}")
    review = item.get("review") if isinstance(item.get("review"), dict) else {}
    if clean_text(review.get("notes")):
        lines.append("審稿備註：" + clean_text(review.get("notes"), 600))
    notes = item.get("personal_notes")
    if isinstance(notes, dict) and clean_text(notes.get("body")):
        lines.append("我的關鍵紀錄：" + clean_text(notes.get("body"), 600))
    requests = item.get("skill_requests") if isinstance(item.get("skill_requests"), list) else []
    for request in requests[-3:]:
        lines.append(f"重送 skill：{clean_text(request.get('requested_at'))} / {clean_text(request.get('personal_notes'), 240)}")
    if not lines:
        return "<p class='lede'>目前沒有本機編輯紀錄。</p>"
    return "<ul>" + "".join(f"<li>{h(line)}</li>" for line in lines) + "</ul>"


def metadata_html(item: dict) -> str:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    rows = [
        ("original_site_title", "原始網站標題", metadata.get("original_site_title") or metadata.get("title") or item.get("title")),
        ("original_language", "原始語言", metadata.get("original_language")),
        ("translated_zh_title", "自動翻譯中文標題", metadata.get("translated_zh_title")),
        ("original_author", "原始作者", metadata.get("original_author") or item.get("author")),
        ("original_license", "原始網站授權", metadata.get("original_license")),
    ]
    items = []
    for key, label, value in rows:
        text = clean_text(value, 520)
        if not text:
            text = "未標示"
        source = clean_text(metadata.get(f"{key}_source"), 120)
        items.append(f"<li><strong>{h(label)}</strong>：{h(text)}{f'（{h(source)}）' if source else ''}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def article_page(item: dict, repo_url: str, branch: str) -> str:
    kind = item_display_kind(item)
    body_markdown = item_body_markdown(item)
    article_html = markdown_to_html(body_markdown) if body_markdown else "<p class='empty'>這篇目前還沒有本機全文。回本機閱讀區按「展開全文」後重新產生 GH Pages 閱讀版，就會帶入這裡。</p>"
    note_key = h(clean_text(item.get("id")))
    source_url = clean_text(item.get("url"))
    side = f"""
<aside class="side-panel">
  <h2>我的關鍵紀錄</h2>
  <textarea id="note-body" placeholder="寫下你想留下的判斷、疑問、台灣脈絡或後續撰稿角度。"></textarea>
  <div class="actions">
    <button type="button" id="note-save">儲存到這台瀏覽器</button>
    <a class="button secondary" href="{h(note_pr_url(item, repo_url, branch))}" target="_blank" rel="noreferrer">用 GitHub 建 PR</a>
  </div>
  <h2>編輯紀錄</h2>
  {edit_record_html(item)}
  <h2>原始 metadata</h2>
  {metadata_html(item)}
</aside>
<script>
const noteKey = "ian-open-news-note:{note_key}";
const noteBody = document.getElementById("note-body");
noteBody.value = localStorage.getItem(noteKey) || "";
document.getElementById("note-save").addEventListener("click", () => {{
  localStorage.setItem(noteKey, noteBody.value);
}});
</script>
"""
    body = f"""
<div class="article-layout">
  <article class="article-panel">
    <div>
      <span class="badge">開放科技</span>
      <span class="badge">{h(content_kind_label(kind))}</span>
      {public_reader_badges(item)}
      {'<span class="badge">已載入本機全文</span>' if body_markdown else '<span class="badge">尚未載入全文</span>'}
      <span class="badge">{h(item_date(item))}</span>
    </div>
    <h2>{h(item_display_title(item))}</h2>
    <p class="lede">{h(item_zh_summary(item, 520))}</p>
    {public_tag_chips(item, 8)}
    <div class="actions">
      <a class="button secondary" href="../index.html">回精選與觀點</a>
      <a class="button secondary" href="../news.html">看小消息</a>
      {f'<a class="button quiet" href="{h(source_url)}" target="_blank" rel="noreferrer">原始連結</a>' if source_url else ''}
    </div>
    <section class="article-body">{article_html}</section>
  </article>
  {side}
</div>
"""
    return page_shell(item_display_title(item) or "單篇文章", body, current="article", depth=1)


def index_page(items: list[dict]) -> str:
    current = [item for item in items if item_is_current_reading(item)]
    primary = [item for item in items if item_display_kind(item) in PRIMARY_KINDS and not item_is_current_reading(item)]
    small_news = [item for item in items if item_display_kind(item) == "small-news" and not item_is_current_reading(item)]
    current_cards = "\n".join(item_card(item) for item in current[:12])
    cards = "\n".join(item_card(item) for item in primary[:120]) or "<p class='empty'>目前沒有精選文章或觀點文章。</p>"
    news_preview = "\n".join(news_row(item) for item in small_news[:8]) or "<p class='empty'>目前沒有小消息。</p>"
    body = f"""
{time_filter_controls()}
{f'''
<section>
  <h2>Ian 近期正在閱讀</h2>
  <p class="lede">最近特別想讀完、整理或分享給大家的文章。</p>
  <div class="card-grid">{current_cards}</div>
</section>
''' if current_cards else ''}
<section>
  <h2>精選文章與觀點文章</h2>
  <p class="lede">這裡優先呈現需要細讀、可能延伸撰稿或觀點整理的內容。</p>
  <div class="card-grid">{cards}</div>
</section>
<section>
  <h2>最新小消息</h2>
  <p class="lede">小消息改成列表，適合快速掃過；完整列表在下一頁。</p>
  <div class="news-list">{news_preview}</div>
  <div class="actions"><a class="button secondary" href="news.html">看全部小消息</a></div>
</section>
<div class="empty" data-time-empty hidden>這個時間範圍沒有可顯示的項目。</div>
"""
    return page_shell("開放科技閱讀版", body, current="index", include_time_filter=True)


def news_page(items: list[dict]) -> str:
    small_news = [item for item in items if item_display_kind(item) == "small-news"]
    rows = "\n".join(news_row(item) for item in small_news) or "<p class='empty'>目前沒有小消息。</p>"
    body = f"""
{time_filter_controls()}
<section>
  <h2>小消息列表</h2>
  <p class="lede">純新聞消息用列表呈現，保留快速掃讀與點進單篇的入口。</p>
  <div class="news-list">{rows}</div>
</section>
<div class="empty" data-time-empty hidden>這個時間範圍沒有可顯示的小消息。</div>
"""
    return page_shell("開放科技小消息", body, current="news", include_time_filter=True)


def write_clean(path: Path, html: str) -> None:
    html = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", html)
    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render GitHub Pages reader pages for open-tech items.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output_dir = args.output.parent
    articles_dir = output_dir / "articles"
    items = [item for item in load_jsonl(args.items) if item_is_public_reader(item)]
    items.sort(key=kind_order, reverse=True)
    items.sort(key=lambda item: {"featured-article": 0, "opinion-article": 1, "small-news": 2}.get(item_display_kind(item), 9))

    repo_url = repo_web_url()
    branch = branch_name()
    write_clean(args.output, index_page(items))
    write_clean(output_dir / "news.html", news_page(items))
    articles_dir.mkdir(parents=True, exist_ok=True)
    for stale in articles_dir.glob("*.html"):
        stale.unlink()
    for item in items:
        write_clean(articles_dir / article_filename(item), article_page(item, repo_url, branch))
    print(f"wrote {output_dir} ({len(items)} items, {len(items)} article pages)")


if __name__ == "__main__":
    main()
