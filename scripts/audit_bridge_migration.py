#!/usr/bin/env python3
"""唯讀盤點 facebook 與 inoreader-monitor 來源的替代路徑建議。

bridge（自架 RSSHub）退場或搬家前，先盤點哪些 facebook 來源其實有
原生 RSS 可以直接改接、哪些只能退回 Google Alert 或手動書籤；
inoreader-monitor 來源則對回 Inoreader 匯出的 OPML，找出關鍵字，
好在 Google Alerts 重建等價的監測。

這支 script 絕不寫 database/：所有輸出都到 .cache/migration-audit.md
與 .cache/migration-audit.jsonl。
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from analyze_source_health import clean_text, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "database" / "sources.jsonl"
OPML = ROOT / "reference" / "Inoreader export 20260618" / "subscriptions.xml"
OUTPUT_MD = ROOT / ".cache" / "migration-audit.md"
OUTPUT_JSONL = ROOT / ".cache" / "migration-audit.jsonl"

# 探測時使用一般瀏覽器 User-Agent，避免被擋。
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
FALLBACK_FEED_PATHS = ["/feed/", "/rss", "/atom.xml", "/index.xml"]
FEED_CONTENT_TYPES = ("xml", "rss", "atom")

# 每個網域之間至少間隔 0.5 秒，對別人的主機有禮貌一點。
_last_request_at: dict[str, float] = {}


def domain_of(url: str) -> str:
    """取出網域（小寫、去掉 www.），取不到就回空字串。"""
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return netloc.removeprefix("www.")


def is_facebook_domain(domain: str) -> bool:
    return domain == "facebook.com" or domain.endswith(".facebook.com") or domain in {"fb.com", "fb.me"}


def polite_request(url: str, timeout: float, method: str = "GET") -> tuple[int, str, str] | None:
    """送出一個 request，回傳 (status, content-type, body 前 200KB)；失敗回 None。"""
    domain = domain_of(url)
    elapsed = time.monotonic() - _last_request_at.get(domain, 0.0)
    if elapsed < 0.5:
        time.sleep(0.5 - elapsed)
    _last_request_at[domain] = time.monotonic()
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            content_type = str(response.headers.get("Content-Type") or "").lower()
            body = "" if method == "HEAD" else response.read(200_000).decode("utf-8", errors="replace")
            return status, content_type, body
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        # DNS 失敗、連線超時、4xx/5xx（HTTPError 是 URLError 子類）都不算命中，也不中斷整體。
        return None


def find_feed_links_in_html(html: str, base_url: str) -> list[str]:
    """從 HTML 找 <link rel="alternate" type="...rss/atom/xml..."> 宣告的 feed。"""
    feeds = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.IGNORECASE):
        rel = re.search(r"""rel\s*=\s*["']([^"']+)["']""", tag, flags=re.IGNORECASE)
        link_type = re.search(r"""type\s*=\s*["']([^"']+)["']""", tag, flags=re.IGNORECASE)
        href = re.search(r"""href\s*=\s*["']([^"']+)["']""", tag, flags=re.IGNORECASE)
        if not (rel and link_type and href):
            continue
        if "alternate" not in rel.group(1).lower():
            continue
        if not any(marker in link_type.group(1).lower() for marker in FEED_CONTENT_TYPES):
            continue
        feeds.append(urljoin(base_url, href.group(1)))
    return feeds


def probe_native_feed(site_url: str, timeout: float) -> str | None:
    """探測 site_url 有沒有原生 feed：先看 HTML 宣告，再試常見路徑。"""
    result = polite_request(site_url, timeout)
    if result:
        status, _, body = result
        if 200 <= status < 300:
            feeds = find_feed_links_in_html(body, site_url)
            if feeds:
                return feeds[0]
    base = site_url.rstrip("/")
    for path in FALLBACK_FEED_PATHS:
        candidate = base + path
        # 先 HEAD，主機不支援再退回 GET。
        result = polite_request(candidate, timeout, method="HEAD")
        if result is None:
            result = polite_request(candidate, timeout)
        if result is None:
            continue
        status, content_type, _ = result
        if 200 <= status < 300 and any(marker in content_type for marker in FEED_CONTENT_TYPES):
            return candidate
    return None


def google_alert_query_for(source: dict) -> str:
    """給 facebook 來源一個 Google Alert 建議查詢字串。"""
    site_domain = domain_of(str(source.get("site_url") or ""))
    if site_domain and not is_facebook_domain(site_domain):
        return f"site:{site_domain}"
    keyword = clean_text(source.get("name"))
    keyword = re.sub(r"[（(]\s*Facebook\s*[）)]\s*$", "", keyword, flags=re.IGNORECASE).strip()
    return keyword or clean_text(source.get("id"))


def health_counts(source: dict) -> tuple[int, int]:
    assessment = source.get("health_assessment") if isinstance(source.get("health_assessment"), dict) else {}
    counts = assessment.get("counts") if isinstance(assessment.get("counts"), dict) else {}
    return int(counts.get("accepted_total") or 0), int(counts.get("rejected_total") or 0)


def audit_facebook_source(source: dict, probe: bool, timeout: float) -> dict:
    site_url = clean_text(source.get("site_url"))
    site_domain = domain_of(site_url)
    has_native_candidate = bool(site_url) and not is_facebook_domain(site_domain)
    accepted_total, rejected_total = health_counts(source)

    probed = False
    found_feed = None
    notes = []
    if has_native_candidate:
        if probe:
            probed = True
            found_feed = probe_native_feed(site_url, timeout)
            if not found_feed:
                notes.append("探測不到原生 feed")
        else:
            notes.append("未探測原生 feed（--no-probe），建議先跑 --probe 或手動確認")
    elif site_url:
        notes.append("site_url 是 facebook 網域，沒有原生 feed 可探")
    else:
        notes.append("沒有 site_url")

    if found_feed:
        suggestion = "native-rss"
    else:
        suggestion = "google-alert"
        notes.append("若 Google Alert 覆蓋不到，改用 manual-bookmarklet 手動收藏")

    archive_flag = accepted_total == 0 and rejected_total == 0
    if archive_flag:
        notes.append("建議 archive（無歷史價值訊號）")

    return {
        "source_id": source.get("id"),
        "name": clean_text(source.get("name")),
        "source_type": "facebook",
        "status": clean_text(source.get("status")),
        "site_url": site_url,
        "feed_url": clean_text(source.get("feed_url")),
        "accepted_total": accepted_total,
        "rejected_total": rejected_total,
        "probed": probed,
        "suggestion": suggestion,
        "suggested_feed_url": found_feed,
        "google_alert_query": None if found_feed else google_alert_query_for(source),
        "archive_flag": archive_flag,
        "notes": "；".join(notes),
    }


def load_opml_monitor_titles(opml_path: Path) -> dict[str, str]:
    """從 Inoreader OPML 匯出建 keyword-monitoring id → title 對照表。"""
    if not opml_path.exists():
        print(f"警告：找不到 OPML 匯出 {opml_path}，inoreader-monitor 全數需人工確認。")
        return {}
    try:
        tree = ET.parse(opml_path)
    except ET.ParseError as exc:
        print(f"警告：OPML 解析失敗 {opml_path}: {exc}")
        return {}
    titles = {}
    for outline in tree.iter("outline"):
        xml_url = outline.get("xmlUrl") or ""
        match = re.search(r"keyword-monitoring-(\d+)", xml_url)
        if match:
            titles[match.group(1)] = clean_text(outline.get("title") or outline.get("text"))
    return titles


def audit_inoreader_source(source: dict, monitor_titles: dict[str, str]) -> dict:
    feed_url = clean_text(source.get("feed_url"))
    match = re.search(r"keyword-monitoring-(\d+)", feed_url)
    monitor_id = match.group(1) if match else None
    keyword = monitor_titles.get(monitor_id) if monitor_id else None
    if keyword:
        instruction = (
            f"到 google.com/alerts 建立快訊：關鍵字「{keyword}」、頻率選「隨時」、遞送選 RSS，"
            "然後在 /sources/new 以 source_type=google-alert 新增"
        )
    else:
        instruction = "OPML 找不到對應 outline，需人工回 Inoreader 匯出確認關鍵字"
    return {
        "source_id": source.get("id"),
        "name": clean_text(source.get("name")),
        "source_type": "inoreader-monitor",
        "status": clean_text(source.get("status")),
        "feed_url": feed_url,
        "monitor_id": monitor_id,
        "keyword": keyword,
        "suggestion": "google-alert" if keyword else "需人工確認",
        "instruction": instruction,
    }


def md_escape(text: str) -> str:
    return clean_text(text).replace("|", "\\|")


def render_markdown(facebook_rows: list[dict], inoreader_rows: list[dict], probe: bool) -> str:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Bridge 遷移盤點報告",
        "",
        f"- 產生時間：{generated_at}",
        f"- 探測模式：{'有連網探測' if probe else '離線（--no-probe，未探測原生 feed）'}",
        "- 本報告為唯讀盤點，未改動 database/ 任何檔案。",
        "",
        "## 總覽",
        "",
        "| 分類 | 建議 | 筆數 |",
        "| --- | --- | --- |",
    ]
    fb_native = sum(1 for row in facebook_rows if row["suggestion"] == "native-rss")
    fb_alert = sum(1 for row in facebook_rows if row["suggestion"] == "google-alert")
    fb_archive = sum(1 for row in facebook_rows if row["archive_flag"])
    ino_alert = sum(1 for row in inoreader_rows if row["suggestion"] == "google-alert")
    ino_manual = sum(1 for row in inoreader_rows if row["suggestion"] == "需人工確認")
    lines += [
        f"| facebook | native-rss（探到原生 feed） | {fb_native} |",
        f"| facebook | google-alert / manual-bookmarklet | {fb_alert} |",
        f"| facebook | 建議 archive（無歷史價值訊號） | {fb_archive} |",
        f"| inoreader-monitor | google-alert（已對回關鍵字） | {ino_alert} |",
        f"| inoreader-monitor | 需人工回 Inoreader 匯出確認 | {ino_manual} |",
        "",
        "## inoreader-monitor 遷移 checklist",
        "",
    ]
    if not inoreader_rows:
        lines.append("（沒有 inoreader-monitor 來源）")
    for row in inoreader_rows:
        lines.append(f"- [ ] {row['name']}（{row['source_id']}）：{row['instruction']}")
    lines += [
        "",
        "## facebook 來源逐筆",
        "",
        "| name | site_url | 建議 | 探測到的 feed | 備註 |",
        "| --- | --- | --- | --- | --- |",
    ]
    if not facebook_rows:
        lines.append("| （沒有 facebook 來源） | | | | |")
    for row in facebook_rows:
        suggestion = row["suggestion"]
        if row["google_alert_query"]:
            suggestion += f"（查詢：{md_escape(row['google_alert_query'])}）"
        lines.append(
            "| {name} | {site} | {suggestion} | {feed} | {notes} |".format(
                name=md_escape(row["name"]),
                site=md_escape(row["site_url"]) or "—",
                suggestion=suggestion,
                feed=md_escape(row["suggested_feed_url"] or "—"),
                notes=md_escape(row["notes"]),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="唯讀盤點 facebook 與 inoreader-monitor 來源的替代路徑。")
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--probe", action=argparse.BooleanOptionalAction, default=True,
                        help="是否連網探測原生 feed（--no-probe 可離線跑）")
    parser.add_argument("--timeout", type=float, default=10.0, help="單一 request 超時秒數")
    parser.add_argument("--output-md", type=Path, default=OUTPUT_MD)
    parser.add_argument("--output-jsonl", type=Path, default=OUTPUT_JSONL)
    args = parser.parse_args()

    sources = load_jsonl(args.sources)
    facebook_sources = [source for source in sources if source.get("source_type") == "facebook"]
    inoreader_sources = [source for source in sources if source.get("source_type") == "inoreader-monitor"]
    print(f"facebook 來源 {len(facebook_sources)} 筆、inoreader-monitor 來源 {len(inoreader_sources)} 筆。")

    facebook_rows = []
    for index, source in enumerate(facebook_sources, start=1):
        if args.probe:
            print(f"[{index}/{len(facebook_sources)}] 探測 {clean_text(source.get('name'))} ...")
        facebook_rows.append(audit_facebook_source(source, args.probe, args.timeout))
    # 排序：曾有 accepted 記錄者排前面，status=active 排前面。
    facebook_rows.sort(key=lambda row: (row["accepted_total"] == 0, row["status"] != "active", row["name"]))

    monitor_titles = load_opml_monitor_titles(OPML)
    inoreader_rows = [audit_inoreader_source(source, monitor_titles) for source in inoreader_sources]

    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(render_markdown(facebook_rows, inoreader_rows, args.probe), encoding="utf-8")
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.output_jsonl.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in [*facebook_rows, *inoreader_rows]),
        encoding="utf-8",
    )

    print(f"報告已寫到 {args.output_md}")
    print(f"機器可讀版已寫到 {args.output_jsonl}")


if __name__ == "__main__":
    main()
