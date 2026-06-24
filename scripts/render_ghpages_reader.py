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
    item_article_markdown,
    item_current_reading_age_days,
    item_display_time,
    item_display_title,
    item_is_current_reading,
    is_reader_item,
    item_display_kind,
    item_image_url,
    item_sort_time,
    item_translated_markdown,
    item_visible_tags,
    item_zh_summary,
    load_jsonl,
    markdown_to_html,
    normalized_title_key,
    public_reader_article_filename,
    reader_month_key,
    reader_period_key,
    reader_period_label,
    strip_duplicate_leading_heading,
    track_meta,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "reader" / "index.html"
PUBLIC_KINDS = {"featured-article", "small-news", "opinion-article"}
PRIMARY_KINDS = {"featured-article", "opinion-article"}
CONFLICT_COPY_RE = re.compile(r" .*\d+\.html$")
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
    return public_reader_article_filename(item)


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
    translated = item_translated_markdown(item)
    if translated:
        return translated
    return item_article_markdown(item)


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


def reader_badge(label: str, class_name: str = "neutral") -> str:
    return f'<span class="badge badge--{h(class_name)}">{h(label)}</span>'


def reader_kind_badge(kind: str) -> str:
    class_name = {
        "featured-article": "suggest-keep",
        "opinion-article": "opinion",
        "small-news": "small-news",
    }.get(kind, "neutral")
    return reader_badge(content_kind_label(kind), class_name)


def reader_status_badges(item: dict, has_body: bool) -> str:
    track_label = track_meta(item.get("track", ""))["short"]
    return (
        reader_badge(track_label, "opentech")
        + reader_kind_badge(item_display_kind(item))
        + public_reader_badges(item)
        + reader_badge(item_date(item), "date")
    )


def public_tag_chips(item: dict, limit: int = 6) -> str:
    tags = item_visible_tags(item, limit)
    if not tags:
        return ""
    return '<div class="tag-chip-list">' + "".join(f'<span class="tag-chip">{h(tag)}</span>' for tag in tags) + "</div>"


def public_help_dot(text: str) -> str:
    text = clean_text(text, 500)
    return f'<span class="help-dot" title="{h(text)}">?</span>' if text else ""


def kind_order(item: dict) -> tuple[int, str, str, str]:
    kind = item_display_kind(item)
    order = {"featured-article": 0, "opinion-article": 1, "small-news": 2}.get(kind, 9)
    return (order, item_sort_time(item), item_display_title(item), clean_text(item.get("id")))


def reader_homepage_order(items: list[dict]) -> list[dict]:
    ordered_groups = [
        [item for item in items if item_is_current_reading(item)],
        [item for item in items if item_display_kind(item) in PRIMARY_KINDS and not item_is_current_reading(item)],
        [item for item in items if item_display_kind(item) == "small-news" and not item_is_current_reading(item)],
        [item for item in items if item_display_kind(item) not in PUBLIC_KINDS],
    ]
    seen: set[str] = set()
    ordered: list[dict] = []
    for group in ordered_groups:
        for item in group:
            item_id = clean_text(item.get("id"))
            if item_id and item_id in seen:
                continue
            if item_id:
                seen.add(item_id)
            ordered.append(item)
    return ordered


def article_sequence_nav(previous_item: dict | None, next_item: dict | None) -> str:
    links = []
    if previous_item:
        links.append(
            f"""
<a class="article-sequence-link" href="{h(article_href(previous_item, from_article=True))}">
  <span class="article-sequence-label">上一則</span>
  <span class="article-sequence-title">{h(clean_text(item_display_title(previous_item), 72))}</span>
</a>
"""
        )
    if next_item:
        links.append(
            f"""
<a class="article-sequence-link" href="{h(article_href(next_item, from_article=True))}">
  <span class="article-sequence-label">下一則</span>
  <span class="article-sequence-title">{h(clean_text(item_display_title(next_item), 72))}</span>
</a>
"""
        )
    if not links:
        return ""
    return '<nav class="article-sequence-nav" aria-label="前後文章">' + "".join(links) + "</nav>"


def period_sections(items: list[dict], renderer, container_class: str, empty: str) -> str:
    if not items:
        return f"<p class='empty'>{h(empty)}</p>"
    month_keys: list[str] = []
    for item in items:
        key = reader_month_key(item)
        if key not in month_keys:
            month_keys.append(key)
    month_index = {key: index for index, key in enumerate(month_keys)}
    groups: list[tuple[str, int, list[dict]]] = []
    group_index: dict[str, int] = {}
    for item in items:
        label = reader_period_label(item)
        item_month_index = month_index.get(reader_month_key(item), 999)
        if label not in group_index:
            group_index[label] = len(groups)
            groups.append((label, item_month_index, []))
        label_text, current_month_index, records = groups[group_index[label]]
        records.append(item)
        groups[group_index[label]] = (label_text, min(current_month_index, item_month_index), records)
    sections = []
    for label, item_month_index, records in groups:
        hidden = " hidden" if item_month_index >= 1 else ""
        sections.append(
            f"""
<details class="reader-period" data-reader-period data-month-index="{item_month_index}" id="{h(reader_period_key(records[0]))}" open{hidden}>
  <summary>
    <h2><span class="reader-period-heading-label">{h(label)}</span></h2>
    <p class="reader-period-count">{len(records)} 筆</p>
  </summary>
  <div class="{h(container_class)}">{''.join(renderer(item) for item in records)}</div>
</details>
"""
        )
    more = ""
    if len(month_keys) > 1:
        more = '<div class="actions reader-more-row"><button type="button" class="secondary" data-reader-more-months>more：再載入 1 個月</button></div>'
    return "".join(sections) + more


def period_more_script() -> str:
    return """
<script>
(() => {
  const button = document.querySelector("[data-reader-more-months]");
  if (!button) return;
  let visibleMonths = 1;
  function sync() {
    const sections = Array.from(document.querySelectorAll("[data-reader-period]"));
    let hiddenCount = 0;
    sections.forEach((section) => {
      const monthIndex = Number(section.dataset.monthIndex || "999");
      const hide = monthIndex >= visibleMonths;
      section.hidden = hide;
      if (hide) hiddenCount += 1;
    });
    button.hidden = hiddenCount === 0;
  }
  button.addEventListener("click", () => {
    visibleMonths += 1;
    sync();
  });
  sync();
})();
</script>
"""


def note_pr_url(item: dict, repo_url: str, branch: str) -> str:
    return f"{repo_url}/new/{branch}/reader-notes?filename={clean_text(item.get('id')) or 'item'}.md"


def page_shell(title: str, body: str, current: str = "index", depth: int = 0, include_time_filter: bool = False) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    root_prefix = "../" if depth else ""
    nav = f"""
<nav class="reader-nav" aria-label="閱讀版導覽">
  <a class="{h('is-active' if current == 'index' else '')}" href="{root_prefix}index.html">精選與觀點</a>
  <a class="{h('is-active' if current == 'news' else '')}" href="{root_prefix}news.html">小消息</a>
</nav>
"""
    page_heading = "" if current == "article" else f'<section class="page-heading"><h1>{h(title)}</h1></section>'
    return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)} - Ian Open News</title>
  <style>
    @import url("https://fonts.googleapis.com/css2?family=Noto+Serif:wght@260;400;550;600;700&family=Noto+Serif+TC:wght@260;400;550;600;700&display=swap");
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
      --paper: #fffdf7;
      --article-serif: "Noto Serif", "Noto Serif Traditional Chinese", "Noto Serif TC", "Noto Serif CJK TC", "Source Han Serif TC", "PingFang TC", serif;
      --article-heading: "LINE Seed TW", "LINE Seed Sans TW", "Noto Sans TC", "PingFang TC", sans-serif;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "PingFang TC", "Noto Sans TC", "Microsoft JhengHei", sans-serif;
      line-height: 1.62;
    }}
    .site-header {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(255,255,255,.94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(12px);
    }}
    .masthead {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 14px 22px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }}
    .brand {{
      color: var(--accent);
      font-weight: 900;
      text-decoration: none;
      font-size: 18px;
    }}
    .brand:hover {{ color: var(--ink); }}
    .header-actions {{ display: flex; align-items: center; gap: 8px; }}
    .site-menu {{ position: relative; }}
    .site-menu summary {{
      list-style: none;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 7px 10px;
      font-weight: 850;
      line-height: 1;
    }}
    .site-menu summary::-webkit-details-marker {{ display: none; }}
    .site-menu summary:hover,
    .site-menu[open] summary {{ background: var(--soft); border-color: #c8ccef; }}
    .reader-help summary {{
      width: 36px;
      padding: 0;
      border-radius: 999px;
      color: var(--accent);
    }}
    .site-popover {{
      position: absolute;
      right: 0;
      top: calc(100% + 8px);
      width: min(300px, calc(100vw - 32px));
      padding: 10px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 14px 32px rgba(15,25,35,.16);
      z-index: 30;
    }}
    .reader-help-panel p {{ margin: 0 0 8px; color: var(--muted); font-size: 13px; }}
    .reader-help-panel p:last-child {{ margin-bottom: 0; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 22px; }}
    .page-heading {{ margin: 4px 0 18px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 42px); letter-spacing: 0; line-height: 1.18; }}
    h2 {{ margin: 0 0 8px; font-size: 22px; letter-spacing: 0; line-height: 1.3; }}
    h3 {{ margin: 0 0 6px; letter-spacing: 0; line-height: 1.35; }}
    p {{ margin: 8px 0; }}
    a {{ color: var(--link); overflow-wrap: anywhere; text-underline-offset: 2px; }}
    a:hover {{ color: var(--accent); }}
    .reader-nav {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .site-popover.reader-nav {{ display: grid; }}
    .reader-nav a, .button, button {{
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
    .reader-nav a:hover, .button:hover, button:hover {{ color: #fff; }}
    .reader-nav a:not(.is-active), .button.secondary {{ background: var(--cyan); }}
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
    .badge--opentech, .badge--suggest-keep {{ background: #ece8ff; color: var(--accent); }}
    .badge--opinion {{ background: #eef1fb; color: #273244; }}
    .badge--neutral {{ background: #e7f5fc; color: #00699f; }}
    .badge--small-news, .badge--date {{ background: #fff8db; color: #7a5a00; }}
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
    .tag-chip::before {{
      content: "#";
      color: var(--accent);
      font-weight: 900;
    }}
    .help-dot {{
      display: inline-grid;
      place-items: center;
      width: 18px;
      height: 18px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      font-weight: 900;
      vertical-align: middle;
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
    .story-card h2 a {{
      text-decoration: none;
    }}
    .story-card h2 a:hover {{
      text-decoration: underline;
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
    .reader-period {{
      margin: 0 0 24px;
    }}
    .reader-period > summary {{
      cursor: pointer;
      list-style: none;
    }}
    .reader-period > summary::-webkit-details-marker {{ display: none; }}
    .reader-period h2 {{
      position: relative;
      display: grid;
      place-items: center;
      margin: 22px 0 2px;
      color: #a3abb8;
      font-size: 20px;
      font-weight: 900;
      letter-spacing: 0;
      text-align: center;
      text-shadow: 0 1px 0 #fff, 0 -1px 0 rgba(15,25,35,.08);
    }}
    .reader-period h2::before {{
      content: "";
      position: absolute;
      left: 0;
      right: 0;
      top: 50%;
      height: 1px;
      background: linear-gradient(90deg, transparent, var(--line), transparent);
      z-index: 0;
    }}
    .reader-period-heading-label {{
      position: relative;
      z-index: 1;
      padding: 0 14px;
      background: var(--bg);
    }}
    .reader-period-heading-label::after {{
      content: "收合";
      margin-left: 8px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
    }}
    .reader-period:not([open]) .reader-period-heading-label::after {{
      content: "展開";
    }}
    .reader-period-count {{
      position: relative;
      z-index: 1;
      width: max-content;
      margin: -4px auto 10px;
      padding: 0 10px;
      background: var(--bg);
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }}
    .reader-period[hidden] {{
      display: none !important;
    }}
    .reader-more-row {{
      justify-content: center;
      margin: 8px 0 30px;
    }}
    .article-top-nav {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0 0 14px;
    }}
    .article-back-button {{
      background: #273244;
      box-shadow: 0 8px 22px rgba(15,25,35,.10);
    }}
    .article-sidebar-toggle {{
      margin-left: auto;
      padding: 9px 11px;
    }}
    .article-sidebar-toggle-icon {{
      display: inline-grid;
      place-items: center;
      width: 18px;
      height: 18px;
    }}
    .article-sidebar-toggle-icon svg {{
      width: 18px;
      height: 18px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .article-layout {{ display: grid; grid-template-columns: minmax(0, 760px) minmax(280px, 360px); gap: 18px; align-items: start; }}
    .article-layout.is-sidebar-hidden {{ grid-template-columns: minmax(0, 1fr); }}
    .article-layout.is-sidebar-hidden .side-panel {{ display: none; }}
    .article-main {{ display: grid; gap: 18px; min-width: 0; }}
    .article-summary-card, .article-fulltext-card, .side-panel {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .article-summary-card h1 {{
      font-size: clamp(30px, 4.4vw, 46px);
      line-height: 1.16;
      margin: 8px 0 10px;
    }}
    .article-summary-meta {{ margin-bottom: 8px; }}
    .article-title-link {{
      color: var(--ink);
      text-decoration: none;
    }}
    .article-title-link:hover {{
      color: var(--link);
      text-decoration: underline;
    }}
    .section-kicker {{
      color: var(--accent);
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0;
      margin-bottom: 4px;
    }}
    .article-fulltext-card {{
      background: var(--paper);
      box-shadow: 0 14px 34px rgba(58,45,18,.10), 0 1px 0 rgba(255,255,255,.9) inset;
    }}
    .article-text {{
      color: #17212f;
      font-family: var(--article-serif);
      font-size: 16px;
      font-weight: 260;
      letter-spacing: 0;
      line-height: 2.05;
      font-kerning: normal;
      font-variant-ligatures: common-ligatures contextual;
    }}
    .article-text img {{ max-width: 100%; height: auto; border-radius: 6px; }}
    .article-text pre {{ white-space: pre-wrap; overflow: auto; background: #162024; color: #eaf1ec; padding: 12px; border-radius: 8px; }}
    .article-text blockquote {{
      margin: 1.1em 0;
      padding: .75em 1em;
      border-left: 4px solid var(--cyan);
      background: #f7fbfe;
      color: #30445f;
    }}
    .article-text h1,
    .article-text h2,
    .article-text h3,
    .article-text h4,
    .article-text h5 {{
      font-family: var(--article-heading);
      font-weight: 850;
      line-height: 1.35;
      letter-spacing: 0;
      margin: 1.55em 0 .68em;
    }}
    .article-text h1 {{ color: var(--accent); font-size: 28px; margin-top: 0; }}
    .article-text h2 {{
      color: var(--accent);
      font-size: 22px;
      padding-bottom: 7px;
      border-bottom: 1px solid rgba(100,80,220,.24);
    }}
    .article-text h3 {{
      color: var(--accent);
      font-size: 19px;
      padding-left: 12px;
      border-left: 3px solid var(--accent);
    }}
    .article-text h4 {{
      color: #0f1923;
      font-size: 17px;
      padding-bottom: 4px;
      border-bottom: 1px dashed rgba(15,25,35,.22);
    }}
    .article-text h5 {{ color: #0f1923; font-size: 15px; }}
    .article-text p {{ margin: 0 0 1.25em; }}
    .article-text ul, .article-text ol {{ margin: 0 0 1.25em 1.4em; padding: 0; }}
    .article-text li {{ margin: .45em 0; }}
    .article-text strong,
    .article-text b,
    .article-text a {{ font-weight: 550; }}
    .side-panel {{
      position: sticky;
      top: 84px;
    }}
    .side-panel h2 {{ font-size: 18px; margin-top: 18px; }}
    .side-panel h2:first-child {{ margin-top: 0; }}
    .reader-history {{
      margin-top: 22px;
      padding-top: 12px;
      border-top: 1px solid #e8eaf0;
      color: #8a93a2;
      font-size: 12px;
      line-height: 1.55;
    }}
    .reader-history > strong {{
      color: #7c8594;
      font-size: 12px;
    }}
    .reader-history p {{ margin: 5px 0 0; }}
    .reader-history ul {{ margin: 5px 0 0; padding-left: 18px; }}
    .reader-history li {{ margin: 3px 0; }}
    .article-sequence-nav {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 2px 0 10px;
    }}
    .article-sequence-link {{
      min-height: 72px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      text-decoration: none;
      box-shadow: 0 8px 22px rgba(15,25,35,.10);
    }}
    .article-sequence-link:hover {{
      border-color: var(--cyan);
      color: #00699f;
      background: #eefcff;
    }}
    .article-sequence-label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      margin-bottom: 4px;
    }}
    .article-sequence-title {{
      display: block;
      font-weight: 850;
      line-height: 1.35;
    }}
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
      .article-sequence-nav {{ grid-template-columns: 1fr; }}
      .side-panel {{ position: static; }}
    }}
  </style>
</head>
<body>
  <header class="site-header">
    <div class="masthead">
      <a class="brand" href="{root_prefix}index.html">Ian Open News</a>
      <div class="header-actions">
        <details class="site-menu reader-help">
          <summary aria-label="閱讀版說明">?</summary>
          <div class="site-popover reader-help-panel">
            <p>開放科技閱讀版。首頁優先放精選文章與觀點文章，小消息改用列表頁快速掃讀。</p>
            <p class="generated">產生時間：{h(generated_at)}</p>
          </div>
        </details>
        <details class="site-menu reader-menu">
          <summary>Menu</summary>
          <div class="site-popover">
            {nav}
          </div>
        </details>
      </div>
    </div>
  </header>
  <main>{page_heading}{body}</main>
  {period_more_script()}
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
    <div>{reader_status_badges(item, has_body)}</div>
    <h2><a href="{h(article_href(item))}">{h(item_display_title(item))}</a></h2>
    <p class="summary">{h(summary)}</p>
    {public_tag_chips(item)}
  </div>
</article>
"""


def news_row(item: dict, depth: int = 0) -> str:
    prefix = "../" if depth else ""
    summary = item_zh_summary(item, 220)
    has_body = bool(item_body_markdown(item))
    return f"""
<article class="news-item" data-reader-item data-item-date="{h(item_data_date(item))}">
  <div>{reader_status_badges(item, has_body)}</div>
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
        return "<p>目前沒有公開歷程。</p>"
    return "<ul>" + "".join(f"<li>{h(line)}</li>" for line in lines) + "</ul>"


def metadata_html(item: dict, display_title: str = "") -> str:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    rows = [
        ("original_site_title", "原始網站標題", metadata.get("original_site_title") or metadata.get("title") or item.get("title")),
        ("original_language", "原始語言", metadata.get("original_language")),
        ("translated_zh_title", "自動翻譯中文標題", metadata.get("translated_zh_title")),
        ("original_author", "原始作者", metadata.get("original_author") or item.get("author")),
        ("original_license", "原始網站授權", metadata.get("original_license")),
    ]
    items = []
    display_title_key = normalized_title_key(display_title)
    for key, label, value in rows:
        text = clean_text(value, 520)
        if key == "translated_zh_title" and display_title_key and normalized_title_key(text) == display_title_key:
            continue
        if not text:
            text = "未標示"
        source = clean_text(metadata.get(f"{key}_source"), 120)
        items.append(f"<li><strong>{h(label)}</strong>：{h(text)}{f'（{h(source)}）' if source else ''}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def article_page(item: dict, repo_url: str, branch: str, previous_item: dict | None = None, next_item: dict | None = None) -> str:
    translated_markdown = item_translated_markdown(item)
    body_markdown = translated_markdown or item_article_markdown(item)
    is_translation = bool(translated_markdown)
    note_key = h(clean_text(item.get("id")))
    source_url = clean_text(item.get("url"))
    title = item_display_title(item)
    article_markdown = strip_duplicate_leading_heading(body_markdown, title)
    has_article_markdown = bool(article_markdown)
    fulltext_heading = ("中文全文" if is_translation else "原始主文") if has_article_markdown else "尚未載入全文"
    fulltext_kicker = "中文翻譯" if is_translation else "全文"
    article_html = (
        markdown_to_html(article_markdown)
        if has_article_markdown
        else "<p class='empty'>這篇目前還沒有本機全文。回本機閱讀區按「展開全文」後重新產生 GH Pages 閱讀版，就會帶入這裡。</p>"
    )
    title_html = (
        f'<a class="article-title-link" href="{h(source_url)}" target="_blank" rel="noreferrer" title="開啟原始連結">{h(title)}</a>'
        if source_url
        else h(title)
    )
    side = f"""
<aside class="side-panel">
  <h2>我的關鍵紀錄</h2>
  <textarea id="note-body" placeholder="寫下你想留下的判斷、疑問、台灣脈絡或後續撰稿角度。"></textarea>
  <div class="actions">
    <button type="button" id="note-save">儲存到這台瀏覽器</button>
    <a class="button secondary" href="{h(note_pr_url(item, repo_url, branch))}" target="_blank" rel="noreferrer">用 GitHub 建 PR</a>
  </div>
  <h2>原始 metadata</h2>
  {metadata_html(item, title)}
  <div class="reader-history">
    <strong>歷程</strong>
    {edit_record_html(item)}
  </div>
</aside>
<script>
const noteKey = "ian-open-news-note:{note_key}";
const noteBody = document.getElementById("note-body");
noteBody.value = localStorage.getItem(noteKey) || "";
document.getElementById("note-save").addEventListener("click", () => {{
  localStorage.setItem(noteKey, noteBody.value);
}});
const articleLayout = document.getElementById("public-article-layout");
const articleSidePanel = document.getElementById("public-article-side-panel");
const articleSideToggle = document.getElementById("public-article-side-toggle");
const articleSideToggleLabel = articleSideToggle?.querySelector("[data-sidebar-toggle-label]");
const articleSideStorageKey = "ian-open-news-public-article-sidebar";
const applyArticleSideState = (hidden) => {{
  articleLayout?.classList.toggle("is-sidebar-hidden", hidden);
  articleSidePanel?.setAttribute("aria-hidden", hidden ? "true" : "false");
  articleSideToggle?.setAttribute("aria-expanded", hidden ? "false" : "true");
  if (articleSideToggleLabel) articleSideToggleLabel.textContent = hidden ? "顯示資訊欄" : "隱藏資訊欄";
}};
let articleSideHidden = false;
try {{
  articleSideHidden = localStorage.getItem(articleSideStorageKey) === "hidden";
}} catch (_error) {{
  articleSideHidden = false;
}}
applyArticleSideState(articleSideHidden);
articleSideToggle?.addEventListener("click", () => {{
  articleSideHidden = !articleLayout?.classList.contains("is-sidebar-hidden");
  applyArticleSideState(articleSideHidden);
  try {{
    localStorage.setItem(articleSideStorageKey, articleSideHidden ? "hidden" : "visible");
  }} catch (_error) {{
    // Keep the visual toggle available without storage.
  }}
}});
</script>
"""
    side = side.replace('<aside class="side-panel">', '<aside class="side-panel" id="public-article-side-panel">', 1)
    body = f"""
<nav class="article-top-nav" aria-label="返回">
  <a class="button article-back-button" href="../index.html" onclick="if (history.length > 1) {{ history.back(); return false; }}">返回閱讀版</a>
  <button type="button" class="button quiet article-sidebar-toggle" id="public-article-side-toggle" aria-controls="public-article-side-panel" aria-expanded="true">
    <span class="article-sidebar-toggle-icon" aria-hidden="true">{action_icon("sidebar")}</span>
    <span data-sidebar-toggle-label>隱藏資訊欄</span>
  </button>
</nav>
<div class="article-layout" id="public-article-layout">
  <div class="article-main">
    <article class="article-summary-card">
      <div class="article-summary-meta">{reader_status_badges(item, has_article_markdown)}</div>
      <h1>{title_html}</h1>
      <p class="lede">{h(item_zh_summary(item, 620))}</p>
      {public_tag_chips(item, 8)}
    </article>
    <section class="article-fulltext-card">
      <div class="section-kicker">{h(fulltext_kicker)}</div>
      <h2>{h(fulltext_heading)}</h2>
      <div class="article-text article-markdown">{article_html}</div>
    </section>
    {article_sequence_nav(previous_item, next_item)}
  </div>
  {side}
</div>
"""
    return page_shell(item_display_title(item) or "單篇文章", body, current="article", depth=1)


def index_page(items: list[dict]) -> str:
    current = [item for item in items if item_is_current_reading(item)]
    primary = [item for item in items if item_display_kind(item) in PRIMARY_KINDS and not item_is_current_reading(item)]
    small_news = [item for item in items if item_display_kind(item) == "small-news" and not item_is_current_reading(item)]
    current_cards = "\n".join(item_card(item) for item in current[:12])
    cards = period_sections(primary[:180], item_card, "card-grid", "目前沒有精選文章或觀點文章。")
    news_preview = period_sections(small_news[:80], news_row, "news-list", "目前沒有小消息。")
    body = f"""
{time_filter_controls()}
{f'''
<section>
  <h2>Ian 近期正在閱讀 {public_help_dot("最近特別想讀完、整理或分享給大家的文章。")}</h2>
  <div class="card-grid">{current_cards}</div>
</section>
''' if current_cards else ''}
<section>
  <h2>精選文章與觀點文章 {public_help_dot("這裡優先呈現需要細讀、可能延伸撰稿或觀點整理的內容。")}</h2>
  {cards}
</section>
<section>
  <h2>最新小消息 {public_help_dot("小消息改成列表，適合快速掃過；完整列表在下一頁。")}</h2>
  {news_preview}
</section>
<div class="empty" data-time-empty hidden>這個時間範圍沒有可顯示的項目。</div>
"""
    return page_shell("開放科技閱讀版", body, current="index", include_time_filter=True)


def news_page(items: list[dict]) -> str:
    small_news = [item for item in items if item_display_kind(item) == "small-news"]
    rows = period_sections(small_news, news_row, "news-list", "目前沒有小消息。")
    body = f"""
{time_filter_controls()}
<section>
  <h2>小消息列表 {public_help_dot("純新聞消息用列表呈現，保留快速掃讀與點進單篇的入口。")}</h2>
  {rows}
</section>
<div class="empty" data-time-empty hidden>這個時間範圍沒有可顯示的小消息。</div>
"""
    return page_shell("開放科技小消息", body, current="news", include_time_filter=True)


def write_clean(path: Path, html: str) -> None:
    html = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", html)
    html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == html:
        return
    path.write_text(html, encoding="utf-8")


def cleanup_conflict_copies(articles_dir: Path) -> int:
    removed = 0
    if not articles_dir.exists():
        return removed
    for path in articles_dir.glob("*.html"):
        if CONFLICT_COPY_RE.search(path.name):
            path.unlink()
            removed += 1
    return removed


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
    removed_conflicts = cleanup_conflict_copies(articles_dir)
    expected_files = {article_filename(item) for item in items}
    for stale in articles_dir.glob("*.html"):
        if stale.name not in expected_files:
            stale.unlink()
    ordered_articles = reader_homepage_order(items)
    for index, item in enumerate(ordered_articles):
        previous_item = ordered_articles[index - 1] if index > 0 else None
        next_item = ordered_articles[index + 1] if index < len(ordered_articles) - 1 else None
        write_clean(articles_dir / article_filename(item), article_page(item, repo_url, branch, previous_item, next_item))
    removed_conflicts += cleanup_conflict_copies(articles_dir)
    conflict_note = f", removed {removed_conflicts} duplicate copies" if removed_conflicts else ""
    print(f"wrote {output_dir} ({len(items)} items, {len(items)} article pages{conflict_note})")


if __name__ == "__main__":
    main()
