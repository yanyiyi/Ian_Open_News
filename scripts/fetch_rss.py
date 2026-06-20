#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import xml.etree.ElementTree as ET

from editorial_triage import build_editorial_context, evaluate_editorial_triage
from page_metadata import unwrap_google_alert_url


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
TRIAGE_KEYWORDS = DATABASE / "triage-keywords.json"
DEFAULT_CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DEFAULT_DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"
DEFAULT_REJECTED_ITEMS = DATABASE / "rejected-items.jsonl"
DEFAULT_STATUS_FILE = ROOT / ".cache" / "rss-fetch-status.json"
DEFAULT_SOURCE_TYPES = ["rss", "google-alert", "youtube", "podcast"]


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


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def write_status(path: Path | None, payload: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **payload,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_newline = path.exists() and path.stat().st_size > 0
    if needs_newline:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) != b"\n"
    with path.open("a", encoding="utf-8") as handle:
        if needs_newline:
            handle.write("\n")
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_url_for_match(value: object) -> str:
    url = unwrap_google_alert_url(clean_text(value))
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url.casefold()
    ignored_prefixes = ("utm_",)
    ignored_names = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref"}
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in ignored_names and not key.casefold().startswith(ignored_prefixes)
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.casefold(),
        netloc=parsed.netloc.casefold(),
        fragment="",
        query=urlencode(query, doseq=True),
    )
    return urlunparse(normalized).rstrip("/")


def record_date(record: dict) -> datetime | None:
    for key in ["captured_at", "published_at", "dismissed_at"]:
        parsed = parse_date(clean_text(record.get(key)))
        if parsed:
            return parsed
    return None


def recent_records(records: list[dict], cutoff: datetime) -> list[dict]:
    output = []
    for record in records:
        parsed = record_date(record)
        if parsed and parsed >= cutoff:
            output.append(record)
    return output


def list_field(value: object) -> list[str]:
    if isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = re.split(r"[\n,，]", str(value or ""))
    return [item.strip() for item in raw if item.strip()]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def child_text(element: ET.Element, *names: str) -> str:
    wanted = set(names)
    for child in list(element):
        if local_name(child.tag) in wanted:
            return clean_text("".join(child.itertext()))
    return ""


def child_attr(element: ET.Element, name: str, attr: str, preferred_rel: str = "alternate") -> str:
    fallback = ""
    for child in list(element):
        if local_name(child.tag) != name:
            continue
        value = child.attrib.get(attr, "")
        if not value:
            continue
        if child.attrib.get("rel", preferred_rel) == preferred_rel:
            return value
        if not fallback:
            fallback = value
    return fallback


def attr_text(element: ET.Element, *names: str) -> str:
    wanted = set(names)
    for key, value in element.attrib.items():
        if local_name(key) in wanted:
            return clean_text(value)
    return ""


def category_terms(element: ET.Element) -> list[str]:
    terms: list[str] = []
    for child in list(element):
        if local_name(child.tag) != "category":
            continue
        value = child.attrib.get("term") or clean_text("".join(child.itertext()))
        if value:
            terms.append(value)
    return terms


def parse_date(value: str) -> datetime | None:
    value = clean_text(value)
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", value)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def date_string(value: datetime | None) -> str:
    if not value:
        return ""
    return value.date().isoformat()


@dataclass
class FeedEntry:
    title: str
    url: str
    guid: str
    author: str
    published_at: str
    summary: str
    tags: list[str]


def parse_feed_entries(content: bytes) -> list[FeedEntry]:
    root = ET.fromstring(content.lstrip(b"\xef\xbb\xbf \t\r\n"))
    root_name = local_name(root.tag)
    entries: list[FeedEntry] = []

    if root_name == "rss":
        channel = next((child for child in list(root) if local_name(child.tag) == "channel"), root)
        raw_entries = [child for child in list(channel) if local_name(child.tag) == "item"]
        for item in raw_entries:
            title = child_text(item, "title") or "(無標題)"
            link = child_text(item, "link")
            guid = child_text(item, "guid")
            url = link or guid
            author = child_text(item, "creator", "author")
            published = parse_date(child_text(item, "pubDate", "published", "updated", "date"))
            summary = child_text(item, "encoded", "description", "summary", "content")
            entries.append(
                FeedEntry(
                    title=title,
                    url=url,
                    guid=guid,
                    author=author,
                    published_at=date_string(published),
                    summary=summary,
                    tags=category_terms(item),
                )
            )
    elif root_name == "RDF":
        raw_entries = [child for child in list(root) if local_name(child.tag) == "item"]
        for item in raw_entries:
            title = child_text(item, "title") or "(無標題)"
            link = child_text(item, "link")
            guid = child_text(item, "identifier") or attr_text(item, "about")
            url = link or guid
            author = child_text(item, "creator", "author")
            published = parse_date(child_text(item, "date", "pubDate", "published", "updated"))
            summary = child_text(item, "description", "summary", "encoded", "content")
            entries.append(
                FeedEntry(
                    title=title,
                    url=url,
                    guid=guid,
                    author=author,
                    published_at=date_string(published),
                    summary=summary,
                    tags=category_terms(item),
                )
            )
    elif root_name == "feed":
        raw_entries = [child for child in list(root) if local_name(child.tag) == "entry"]
        for entry in raw_entries:
            title = child_text(entry, "title") or "(無標題)"
            url = child_attr(entry, "link", "href") or child_text(entry, "link")
            guid = child_text(entry, "id")
            author_node = next((child for child in list(entry) if local_name(child.tag) == "author"), None)
            author = child_text(author_node, "name") if author_node is not None else child_text(entry, "author")
            published = parse_date(child_text(entry, "published", "updated", "date"))
            summary = child_text(entry, "summary", "content")
            entries.append(
                FeedEntry(
                    title=title,
                    url=url or guid,
                    guid=guid,
                    author=author,
                    published_at=date_string(published),
                    summary=summary,
                    tags=category_terms(entry),
                )
            )
    else:
        raise ValueError(f"unsupported feed root: {root_name}")

    return [entry for entry in entries if entry.url or entry.guid or entry.title]


def read_feed_bytes(url: str, timeout: int, user_agent: str) -> bytes:
    if url.startswith("file://"):
        return Path(url.removeprefix("file://")).read_bytes()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def default_review() -> dict:
    return {
        "angle": "",
        "research_status": "not-started",
        "structure_review": "pending",
        "line_review": "pending",
        "target_reader_review": "pending",
        "fact_check": "pending",
        "notes": "RSS 自動抓取，待人工分流與審查。",
    }


def normalized(value: object) -> str:
    return clean_text(value).casefold()


def keyword_matches(text: str, keywords: list[str]) -> list[str]:
    haystack = normalized(text)
    matches = []
    for keyword in keywords:
        if normalized(keyword) and normalized(keyword) in haystack:
            matches.append(keyword)
    return list(dict.fromkeys(matches))


def candidate_haystack(record: dict) -> str:
    return "\n".join(
        [
            record.get("title", ""),
            record.get("summary", ""),
            record.get("source_name", ""),
            record.get("author", ""),
            " ".join(str(tag) for tag in record.get("tags", [])),
            record.get("url", ""),
        ]
    )


def evaluate_triage(record: dict, keyword_config: dict) -> dict:
    track = record.get("track", "unclassified")
    track_config = (keyword_config.get("tracks") or {}).get(track, {})
    keep_keywords = track_config.get("keep_keywords") or []
    skip_keywords = track_config.get("skip_keywords") or []
    text = candidate_haystack(record)
    keep_matches = keyword_matches(text, keep_keywords)
    skip_matches = keyword_matches(text, skip_keywords)

    if skip_matches:
        recommendation = "suggest-skip"
        reason = "出現排除關鍵字，先標成建議不要看。"
    elif keep_matches:
        recommendation = "suggest-keep"
        reason = "符合主線關鍵字，建議進候選清單人工看過。"
    else:
        recommendation = "suggest-skip"
        reason = "沒有符合目前主線關鍵字，建議先不要看。"

    return {
        "recommendation": recommendation,
        "reason": reason,
        "matched_keywords": keep_matches,
        "skip_keywords": skip_matches,
        "keyword_config_version": keyword_config.get("version", 1),
    }


def item_record(source: dict, entry: FeedEntry, captured_at: str) -> dict:
    original_url = entry.url or entry.guid
    url = unwrap_google_alert_url(original_url)
    return {
        "id": stable_id("item", url, entry.guid, entry.title),
        "track": source["track"],
        "status": "inbox",
        "priority": "normal",
        "title": clean_text(entry.title, 300) or "(無標題)",
        "url": url,
        "source_id": source["id"],
        "source_name": source["name"],
        "author": clean_text(entry.author, 160),
        "published_at": entry.published_at,
        "captured_at": captured_at,
        "summary": clean_text(entry.summary, 1200),
        "tags": list(dict.fromkeys([source.get("source_group", ""), source.get("source_type", ""), *entry.tags])),
        "origin": "rss-fetch",
        "reference": {
            "feed_url": source.get("feed_url", ""),
            "guid": entry.guid,
            "original_url": original_url if original_url != url else "",
            "source_id": source["id"],
        },
        "review": default_review(),
    }


def source_frequency(source: dict) -> str:
    frequency = clean_text(source.get("fetch_frequency") or "daily").casefold()
    if frequency in {"daily", "weekly", "monthly", "paused"}:
        return frequency
    return "daily"


def source_last_fetch(source: dict) -> datetime | None:
    health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
    for value in [source.get("last_fetched_at"), health.get("last_success_at"), health.get("last_checked_at")]:
        parsed = parse_date(clean_text(value))
        if parsed:
            return parsed
    return None


def source_due_for_fetch(source: dict, now: datetime) -> tuple[bool, str]:
    frequency = source_frequency(source)
    if frequency == "paused":
        return False, "source fetch_frequency is paused"
    last_fetch = source_last_fetch(source)
    if not last_fetch:
        return True, ""
    interval_days = {"daily": 1, "weekly": 7, "monthly": 30}.get(frequency, 1)
    if now - last_fetch < timedelta(days=interval_days):
        return False, f"source fetch_frequency {frequency} is not due yet"
    return True, ""


def source_keyword_filter(record: dict, source: dict) -> tuple[bool, str]:
    required = list_field(source.get("required_keywords"))
    excluded = list_field(source.get("excluded_keywords"))
    text = candidate_haystack(record)
    excluded_matches = keyword_matches(text, excluded)
    if excluded_matches:
        return False, "source excluded keywords matched: " + ", ".join(excluded_matches[:6])
    if required:
        required_matches = keyword_matches(text, required)
        if not required_matches:
            return False, "source required keywords not matched"
    return True, ""


def source_is_fetchable(source: dict, args: argparse.Namespace) -> tuple[bool, str]:
    feed_url = source.get("feed_url", "")
    if source.get("status") != "active":
        return False, "source status is not active"
    if not getattr(args, "force", False):
        due, due_reason = source_due_for_fetch(source, datetime.now(timezone.utc))
        if not due:
            return False, due_reason
    if source.get("source_type") not in args.source_type:
        return False, f"source_type {source.get('source_type')} is not enabled"
    if args.track and source.get("track") not in args.track:
        return False, f"track {source.get('track')} is not enabled"
    if not args.include_unclassified and source.get("track") == "unclassified":
        return False, "unclassified sources are skipped by default"
    if not feed_url.startswith(("http://", "https://", "file://")):
        return False, "feed_url is not directly fetchable"
    return True, ""


def build_report(
    *,
    fetched_sources: int,
    new_items: list[dict],
    failures: list[tuple[dict, str]],
    skipped: list[tuple[dict, str]],
    source_stats: dict[str, dict[str, object]],
    dry_run: bool,
    candidate_mode: bool,
) -> str:
    item_label = "candidates" if candidate_mode else "items"
    mode = "candidate review queue" if candidate_mode else "database inbox"
    lines = [
        "# Daily RSS fetch report",
        "",
        f"- Mode: {'dry run' if dry_run else 'write'} to {mode}",
        f"- Sources fetched: {fetched_sources}",
        f"- New {item_label}: {len(new_items)}",
        f"- Failed sources: {len(failures)}",
        f"- Skipped sources: {len(skipped)}",
        "",
    ]
    if source_stats:
        lines.extend(["## Source handling summary", ""])
        for stats in source_stats.values():
            lines.append(
                "- "
                f"{stats.get('source_name') or stats.get('source_id')} (`{stats.get('source_id')}`): "
                f"seen {stats.get('entries_seen', 0)}, "
                f"new {stats.get('new_items', 0)}, "
                f"old {stats.get('skipped_old', 0)}, "
                f"duplicate recent {stats.get('skipped_duplicate_recent', 0)}, "
                f"source keyword excluded {stats.get('skipped_source_keywords', 0)}, "
                f"status {stats.get('last_fetch_status', 'unknown')}"
            )
        lines.append("")
    if new_items:
        lines.extend([f"## New {item_label}", ""])
        for item in new_items[:80]:
            title = item["title"].replace("\n", " ")
            recommendation = (item.get("triage") or {}).get("recommendation", "")
            suffix = f" ({recommendation})" if recommendation else ""
            lines.append(f"- [{item['track']}] {title}{suffix} - {item.get('url', '')}")
        if len(new_items) > 80:
            lines.append(f"- ...and {len(new_items) - 80} more")
        lines.append("")
    if failures:
        lines.extend(["## Failed sources", ""])
        for source, error in failures[:80]:
            lines.append(f"- {source['name']} (`{source['id']}`): {error}")
        if len(failures) > 80:
            lines.append(f"- ...and {len(failures) - 80} more")
        lines.append("")
    if skipped:
        reasons: dict[str, int] = {}
        for _, reason in skipped:
            reasons[reason] = reasons.get(reason, 0) + 1
        lines.extend(["## Skipped summary", ""])
        for reason, count in sorted(reasons.items()):
            lines.append(f"- {reason}: {count}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch active RSS/Atom feeds into database/items.jsonl")
    parser.add_argument("--sources", type=Path, default=DATABASE / "sources.jsonl")
    parser.add_argument("--items", type=Path, default=DATABASE / "items.jsonl")
    parser.add_argument("--rejected-items", type=Path, default=DEFAULT_REJECTED_ITEMS)
    parser.add_argument("--source-type", action="append", choices=["rss", "google-alert", "youtube", "podcast", "facebook", "inoreader-monitor"], default=[])
    parser.add_argument("--track", action="append", default=[])
    parser.add_argument("--include-unclassified", action="store_true")
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--duplicate-lookback-days", type=int, default=7)
    parser.add_argument("--max-per-source", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--user-agent", default="IanOpenNewsBot/1.0 (+https://github.com/)")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS_FILE)
    parser.add_argument("--force", action="store_true", help="Fetch matching sources even if their frequency is not due yet.")
    parser.add_argument(
        "--candidate-output",
        type=Path,
        help="Write new entries to a local review queue instead of database/items.jsonl.",
    )
    parser.add_argument(
        "--dismissed",
        type=Path,
        default=DEFAULT_DISMISSED,
        help="JSONL file of candidates dismissed locally; used only with --candidate-output.",
    )
    parser.add_argument("--triage-keywords", type=Path, default=TRIAGE_KEYWORDS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-update-source-health", action="store_true")
    parser.add_argument("--fail-on-source-error", action="store_true")
    args = parser.parse_args()

    if not args.source_type:
        args.source_type = DEFAULT_SOURCE_TYPES
    if not args.track:
        args.track = ["digital-humanities-local-knowledge", "open-tech-open-industry"]

    sources = load_jsonl(args.sources)
    existing_items = load_jsonl(args.items)
    rejected_items = load_jsonl(args.rejected_items)
    existing_candidates = load_jsonl(args.candidate_output) if args.candidate_output else []
    dismissed_candidates = load_jsonl(args.dismissed) if args.candidate_output else []
    keyword_config = load_json(args.triage_keywords)
    history_items = [*existing_items, *rejected_items]
    editorial_context = build_editorial_context(history_items, keyword_config)
    duplicate_cutoff = datetime.now(timezone.utc) - timedelta(days=args.duplicate_lookback_days)
    duplicate_history = recent_records(
        [*existing_items, *rejected_items, *existing_candidates, *dismissed_candidates],
        duplicate_cutoff,
    )
    seen_ids = {item.get("id") for item in duplicate_history}
    seen_urls = {normalize_url_for_match(item.get("url")) for item in duplicate_history if item.get("url")}
    seen_guids = {
        (item.get("reference") or {}).get("guid")
        for item in duplicate_history
        if isinstance(item.get("reference"), dict) and (item.get("reference") or {}).get("guid")
    }

    selected_sources: list[dict] = []
    skipped: list[tuple[dict, str]] = []
    source_id_filter = set(args.source_id)
    for source in sources:
        if source_id_filter and source.get("id") not in source_id_filter:
            continue
        fetchable, reason = source_is_fetchable(source, args)
        if fetchable:
            selected_sources.append(source)
        else:
            skipped.append((source, reason))

    write_status(
        args.status_file,
        {
            "phase": "starting",
            "message": f"準備抓取 RSS，符合條件來源 {len(selected_sources)} 個。",
            "selected_sources": len(selected_sources),
            "skipped_sources": len(skipped),
            "candidate_mode": bool(args.candidate_output),
            "source_stats": {},
        },
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    failures: list[tuple[dict, str]] = []
    new_items: list[dict] = []
    fetched_sources = 0
    source_stats: dict[str, dict[str, object]] = {}

    def stats_for(source: dict) -> dict[str, object]:
        source_id = source.get("id", "")
        if source_id not in source_stats:
            source_stats[source_id] = {
                "source_id": source_id,
                "source_name": source.get("name", ""),
                "feed_url": source.get("feed_url", ""),
                "last_checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_fetch_status": "pending",
                "entries_seen": 0,
                "new_items": 0,
                "skipped_old": 0,
                "skipped_duplicate_recent": 0,
                "skipped_source_keywords": 0,
                "last_error": "",
            }
        return source_stats[source_id]

    for source_index, source in enumerate(selected_sources, start=1):
        stats = stats_for(source)
        write_status(
            args.status_file,
            {
                "phase": "fetching",
                "message": f"正在抓取 {source.get('name') or source.get('id')} ({source_index}/{len(selected_sources)})",
                "current_source_id": source.get("id", ""),
                "current_source_name": source.get("name", ""),
                "source_index": source_index,
                "selected_sources": len(selected_sources),
                "fetched_sources": fetched_sources,
                "new_items": len(new_items),
                "failures": len(failures),
                "candidate_mode": bool(args.candidate_output),
                "source_stats": source_stats,
            },
        )
        try:
            content = read_feed_bytes(source["feed_url"], args.timeout, args.user_agent)
            entries = parse_feed_entries(content)
            fetched_sources += 1
            stats["last_fetch_status"] = "ok"
            stats["entries_seen"] = len(entries)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError, OSError) as exc:
            failures.append((source, str(exc)))
            stats["last_fetch_status"] = "failed"
            stats["last_error"] = str(exc)
            write_status(
                args.status_file,
                {
                    "phase": "source-failed",
                    "message": f"{source.get('name') or source.get('id')} 抓取失敗：{exc}",
                    "current_source_id": source.get("id", ""),
                    "current_source_name": source.get("name", ""),
                    "source_index": source_index,
                    "selected_sources": len(selected_sources),
                    "fetched_sources": fetched_sources,
                    "new_items": len(new_items),
                    "failures": len(failures),
                    "candidate_mode": bool(args.candidate_output),
                    "source_stats": source_stats,
                },
            )
            continue

        added_for_source = 0
        for entry in entries:
            published = parse_date(entry.published_at)
            if published and published < cutoff:
                stats["skipped_old"] = int(stats.get("skipped_old") or 0) + 1
                continue
            record = item_record(source, entry, captured_at)
            normalized_record_url = normalize_url_for_match(record.get("url"))
            if record["id"] in seen_ids:
                stats["skipped_duplicate_recent"] = int(stats.get("skipped_duplicate_recent") or 0) + 1
                continue
            if normalized_record_url and normalized_record_url in seen_urls:
                stats["skipped_duplicate_recent"] = int(stats.get("skipped_duplicate_recent") or 0) + 1
                continue
            if entry.guid and entry.guid in seen_guids:
                stats["skipped_duplicate_recent"] = int(stats.get("skipped_duplicate_recent") or 0) + 1
                continue
            passed_source_filter, filter_reason = source_keyword_filter(record, source)
            if not passed_source_filter:
                stats["skipped_source_keywords"] = int(stats.get("skipped_source_keywords") or 0) + 1
                stats["last_source_keyword_reason"] = filter_reason
                continue
            record["triage"] = evaluate_triage(record, keyword_config)
            record["editorial_triage"] = evaluate_editorial_triage(record, keyword_config, editorial_context)
            if args.candidate_output:
                record["candidate_status"] = "pending"
            new_items.append(record)
            seen_ids.add(record["id"])
            if normalized_record_url:
                seen_urls.add(normalized_record_url)
            if entry.guid:
                seen_guids.add(entry.guid)
            added_for_source += 1
            stats["new_items"] = int(stats.get("new_items") or 0) + 1
            if added_for_source >= args.max_per_source:
                break
        excluded_count = int(stats.get("skipped_old") or 0) + int(stats.get("skipped_duplicate_recent") or 0) + int(stats.get("skipped_source_keywords") or 0)
        write_status(
            args.status_file,
            {
                "phase": "source-finished",
                "message": (
                    f"{source.get('name') or source.get('id')} 完成：看過 {stats.get('entries_seen', 0)} 則，"
                    f"新增 {stats.get('new_items', 0)} 則，排除 {excluded_count} 則。"
                ),
                "current_source_id": source.get("id", ""),
                "current_source_name": source.get("name", ""),
                "source_index": source_index,
                "selected_sources": len(selected_sources),
                "fetched_sources": fetched_sources,
                "new_items": len(new_items),
                "failures": len(failures),
                "candidate_mode": bool(args.candidate_output),
                "source_stats": source_stats,
            },
        )

    if not args.dry_run:
        if args.candidate_output:
            append_jsonl(args.candidate_output, new_items)
        else:
            append_jsonl(args.items, new_items)
        if not args.no_update_source_health and source_stats:
            checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            updated_sources = []
            for source in sources:
                stats = source_stats.get(source.get("id"))
                if not stats:
                    updated_sources.append(source)
                    continue
                updated = dict(source)
                previous_health = updated.get("rss_health") if isinstance(updated.get("rss_health"), dict) else {}
                updated["rss_health"] = {**previous_health, **stats, "last_checked_at": checked_at}
                if stats.get("last_fetch_status") == "ok":
                    updated["last_fetched_at"] = checked_at
                    updated["rss_health"]["last_success_at"] = checked_at
                updated_sources.append(updated)
            write_jsonl(args.sources, updated_sources)

    report = build_report(
        fetched_sources=fetched_sources,
        new_items=new_items,
        failures=failures,
        skipped=skipped,
        source_stats=source_stats,
        dry_run=args.dry_run,
        candidate_mode=bool(args.candidate_output),
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
    total_excluded = sum(
        int(stats.get("skipped_old") or 0)
        + int(stats.get("skipped_duplicate_recent") or 0)
        + int(stats.get("skipped_source_keywords") or 0)
        for stats in source_stats.values()
    )
    write_status(
        args.status_file,
        {
            "phase": "finished" if not failures else "finished-with-errors",
            "message": f"RSS 抓取完成：重新抓 {fetched_sources} 個來源，新增 {len(new_items)} 則，排除 {total_excluded} 則。",
            "selected_sources": len(selected_sources),
            "fetched_sources": fetched_sources,
            "new_items": len(new_items),
            "failures": len(failures),
            "skipped_sources": len(skipped),
            "excluded_items": total_excluded,
            "candidate_mode": bool(args.candidate_output),
            "source_stats": source_stats,
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    print(report)

    if failures and args.fail_on_source_error:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
