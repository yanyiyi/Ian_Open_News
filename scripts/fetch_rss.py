#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
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
FEED_ACCEPT_HEADER = "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
BROWSER_FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
FETCH_FREQUENCY_INTERVALS = {
    "hourly": timedelta(hours=1),
    "six-hourly": timedelta(hours=6),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}
FETCH_FREQUENCY_ALIASES = {
    "1h": "hourly",
    "1-hour": "hourly",
    "hour": "hourly",
    "hourly": "hourly",
    "6h": "six-hourly",
    "6-hour": "six-hourly",
    "6-hourly": "six-hourly",
    "six-hour": "six-hourly",
    "six-hourly": "six-hourly",
    "six_hourly": "six-hourly",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
    "manual": "on-update",
    "on-demand": "on-update",
    "on-update": "on-update",
    "on_update": "on-update",
    "paused": "paused",
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


def record_duplicate_urls(record: dict) -> set[str]:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    reference = record.get("reference") if isinstance(record.get("reference"), dict) else {}
    values = [
        record.get("url"),
        metadata.get("canonical_url"),
        metadata.get("final_url"),
        metadata.get("source_url"),
        metadata.get("url_before_update"),
        reference.get("original_url"),
        reference.get("resolved_from_url"),
    ]
    guid = clean_text(reference.get("guid"))
    if guid.startswith(("http://", "https://")):
        values.append(guid)
    return {normalized for value in values if (normalized := normalize_url_for_match(value))}


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


BARE_AMPERSAND_RE = re.compile(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9_.:-]*;)")
INVALID_XML_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Common feed namespace prefixes. Some feeds use a prefix (e.g. media:, content:)
# without declaring it on the root element, which makes a strict parser raise
# "unbound prefix". We re-declare any used-but-missing prefix from this map.
COMMON_FEED_NAMESPACES = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "wfw": "http://wellformedweb.org/CommentAPI/",
    "sy": "http://purl.org/rss/1.0/modules/syndication/",
    "slash": "http://purl.org/rss/1.0/modules/slash/",
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "georss": "http://www.georss.org/georss",
    "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "wp": "http://wordpress.org/export/1.2/",
}
ROOT_TAG_RE = re.compile(r"<(?:rss|feed|rdf:RDF|RDF)\b[^>]*>")


def inject_missing_namespaces(text: str) -> str:
    root = ROOT_TAG_RE.search(text)
    if not root:
        return text
    root_tag = root.group(0)
    used = set(re.findall(r"<\s*([A-Za-z][\w-]*):", text))
    used |= set(re.findall(r"\s([A-Za-z][\w-]*):[\w-]+\s*=", text))
    declared = set(re.findall(r"xmlns:([\w-]+)\s*=", root_tag))
    missing = [p for p in used if p in COMMON_FEED_NAMESPACES and p not in declared]
    if not missing:
        return text
    injection = "".join(f' xmlns:{p}="{COMMON_FEED_NAMESPACES[p]}"' for p in missing)
    repaired = root_tag[:-1] + injection + ">"
    return text[: root.start()] + repaired + text[root.end() :]


def parse_xml_root(content: bytes) -> ET.Element:
    cleaned = content.lstrip(b"\xef\xbb\xbf \t\r\n")
    first_xml = min(
        [index for index in [cleaned.find(marker) for marker in [b"<rss", b"<feed", b"<rdf:RDF", b"<RDF"]] if index >= 0],
        default=-1,
    )
    if first_xml > 0:
        cleaned = cleaned[first_xml:]
    try:
        return ET.fromstring(cleaned)
    except ET.ParseError:
        text = cleaned.decode("utf-8", errors="replace")
        text = INVALID_XML_CHAR_RE.sub(" ", text)
        text = BARE_AMPERSAND_RE.sub("&amp;", text)
        text = inject_missing_namespaces(text)
        return ET.fromstring(text.encode("utf-8"))


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
    root = parse_xml_root(content)
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


def _insecure_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def read_feed_bytes(url: str, timeout: int, user_agent: str) -> bytes:
    if url.startswith("file://"):
        return Path(url.removeprefix("file://")).read_bytes()

    def fetch_with_headers(headers: dict[str, str], context: ssl.SSLContext | None = None) -> bytes:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            content = response.read()
            encoding = clean_text(response.headers.get("Content-Encoding")).casefold()
            if encoding == "gzip" or content.startswith(b"\x1f\x8b"):
                return gzip.decompress(content)
            return content

    default_headers = {"User-Agent": user_agent, "Accept": FEED_ACCEPT_HEADER}
    try:
        return fetch_with_headers(default_headers)
    except urllib.error.HTTPError as exc:
        if exc.code not in {403, 406}:
            raise
    except urllib.error.URLError as exc:
        # Many public-sector feeds (e.g. *.gov.tw) serve a certificate chain that
        # is not in the default trust store. For public RSS, retry without TLS
        # verification rather than dropping the source entirely.
        if not isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise
        return fetch_with_headers(default_headers, context=_insecure_ssl_context())
    return fetch_with_headers(
        {
            "User-Agent": BROWSER_FALLBACK_USER_AGENT,
            "Accept": FEED_ACCEPT_HEADER,
            "Accept-Language": "en-US,en;q=0.9",
        }
    )


LINK_ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(['"])(.*?)\2""", re.S)


def discover_feed_url_from_html(content: bytes, base_url: str) -> str:
    text = content.decode("utf-8", errors="replace")
    if "<html" not in text.casefold() and "<link" not in text.casefold():
        return ""
    for match in re.finditer(r"(?is)<link\b[^>]*>", text):
        attrs = {
            name.casefold(): html.unescape(value.strip())
            for name, _quote, value in LINK_ATTR_RE.findall(match.group(0))
        }
        href = attrs.get("href", "")
        rel = attrs.get("rel", "").casefold()
        media_type = attrs.get("type", "").casefold()
        if href and "alternate" in rel and any(token in media_type for token in ["rss", "atom", "xml"]):
            return urljoin(base_url, href)
    return ""


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
    mechanism_keywords = track_config.get("mechanism_keywords") or []
    text = candidate_haystack(record)
    keep_matches = keyword_matches(text, keep_keywords)
    skip_matches = keyword_matches(text, skip_keywords)
    mechanism_matches = keyword_matches(text, mechanism_keywords)

    if skip_matches:
        recommendation = "suggest-skip"
        reason = "出現排除關鍵字，先標成建議不要看。"
    elif keep_matches:
        recommendation = "suggest-keep"
        reason = "符合主線關鍵字，建議進候選清單人工看過。"
    elif mechanism_matches:
        # 表層主題沒命中主線關鍵字，但命中底層機制框架詞（FOIA、公共數位基礎建設、
        # 開源永續、貢獻者權利、數位人權等）→ 不自主略過，改標成「先問你」並附切角提示。
        recommendation = "suggest-ask"
        reason = (
            "未命中主線關鍵字，但命中底層機制關鍵字「"
            + "、".join(mechanism_matches[:4])
            + "」，可能有切角價值，建議先問你再決定，不要直接略過。"
        )
    else:
        recommendation = "suggest-skip"
        reason = "沒有符合目前主線關鍵字，建議先不要看。"

    return {
        "recommendation": recommendation,
        "reason": reason,
        "matched_keywords": keep_matches,
        "skip_keywords": skip_matches,
        "mechanism_keywords": mechanism_matches,
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
    return FETCH_FREQUENCY_ALIASES.get(frequency, "daily")


def source_last_fetch(source: dict) -> datetime | None:
    health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
    for value in [source.get("last_fetched_at"), health.get("last_success_at"), health.get("last_checked_at")]:
        parsed = parse_date(clean_text(value))
        if parsed:
            return parsed
    return None


def source_has_successful_fetch(source: dict) -> bool:
    health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
    for value in [source.get("last_fetched_at"), health.get("last_success_at")]:
        if parse_date(clean_text(value)):
            return True
    return False


def source_since_days(source: dict, args: argparse.Namespace) -> int:
    if source_has_successful_fetch(source):
        return args.since_days
    return args.initial_since_days


def source_due_for_fetch(source: dict, now: datetime, *, include_on_update: bool = False) -> tuple[bool, str]:
    frequency = source_frequency(source)
    if frequency == "paused":
        return False, "source fetch_frequency is paused"
    if frequency == "on-update":
        if include_on_update:
            return True, ""
        return False, "source fetch_frequency on-update only runs from manual update"
    last_fetch = source_last_fetch(source)
    if not last_fetch:
        return True, ""
    interval = FETCH_FREQUENCY_INTERVALS.get(frequency, FETCH_FREQUENCY_INTERVALS["daily"])
    if now - last_fetch < interval:
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
        due, due_reason = source_due_for_fetch(
            source,
            datetime.now(timezone.utc),
            include_on_update=getattr(args, "include_on_update", False),
        )
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


def source_display_name(source: dict) -> str:
    name = clean_text(source.get("name")) or clean_text(source.get("id")) or "unknown source"
    return re.sub(r"^\s*[-*]\s+", "", name).strip() or name


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
            window = f", window {stats.get('since_days')}d" if stats.get("since_days") else ""
            initial = ", initial" if stats.get("initial_fetch") else ""
            lines.append(
                "- "
                f"{stats.get('source_name') or stats.get('source_id')} (`{stats.get('source_id')}`): "
                f"seen {stats.get('entries_seen', 0)}, "
                f"new {stats.get('new_items', 0)}, "
                f"old {stats.get('skipped_old', 0)}, "
                f"duplicate recent {stats.get('skipped_duplicate_recent', 0)}, "
                f"source keyword excluded {stats.get('skipped_source_keywords', 0)}, "
                f"status {stats.get('last_fetch_status', 'unknown')}{initial}{window}"
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
            lines.append(f"- {source_display_name(source)} (`{source['id']}`): {error}")
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
    parser.add_argument(
        "--initial-since-days",
        type=int,
        default=90,
        help="Use this window for sources that have not had a successful fetch yet.",
    )
    parser.add_argument("--duplicate-lookback-days", type=int, default=7)
    parser.add_argument("--max-per-source", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (compatible; IanOpenNewsBot/1.0; +https://github.com/)",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS_FILE)
    parser.add_argument("--force", action="store_true", help="Fetch matching sources even if their frequency is not due yet.")
    parser.add_argument(
        "--include-on-update",
        action="store_true",
        help="Include sources whose fetch_frequency is on-update; used by manual UI runs.",
    )
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
    duplicate_lookback_days = max(args.duplicate_lookback_days, args.initial_since_days)
    duplicate_cutoff = datetime.now(timezone.utc) - timedelta(days=duplicate_lookback_days)
    duplicate_history = recent_records(
        [*existing_items, *rejected_items, *existing_candidates, *dismissed_candidates],
        duplicate_cutoff,
    )
    seen_ids = {item.get("id") for item in duplicate_history}
    seen_urls = set().union(*(record_duplicate_urls(item) for item in duplicate_history)) if duplicate_history else set()
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
                "source_name": source_display_name(source),
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
                "message": f"正在抓取 {source_display_name(source)} ({source_index}/{len(selected_sources)})",
                "current_source_id": source.get("id", ""),
                "current_source_name": source_display_name(source),
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
            try:
                entries = parse_feed_entries(content)
            except (ET.ParseError, ValueError):
                discovered_feed_url = discover_feed_url_from_html(content, source["feed_url"])
                if not discovered_feed_url or discovered_feed_url == source["feed_url"]:
                    raise
                stats["discovered_feed_url"] = discovered_feed_url
                content = read_feed_bytes(discovered_feed_url, args.timeout, args.user_agent)
                entries = parse_feed_entries(content)
            fetched_sources += 1
            stats["last_fetch_status"] = "ok"
            stats["entries_seen"] = len(entries)
            stats["initial_fetch"] = not source_has_successful_fetch(source)
            stats["since_days"] = source_since_days(source, args)
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
        cutoff = datetime.now(timezone.utc) - timedelta(days=source_since_days(source, args))
        for entry in entries:
            published = parse_date(entry.published_at)
            if published and published < cutoff:
                stats["skipped_old"] = int(stats.get("skipped_old") or 0) + 1
                continue
            record = item_record(source, entry, captured_at)
            normalized_record_urls = record_duplicate_urls(record)
            if record["id"] in seen_ids:
                stats["skipped_duplicate_recent"] = int(stats.get("skipped_duplicate_recent") or 0) + 1
                continue
            if normalized_record_urls and (normalized_record_urls & seen_urls):
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
            seen_urls.update(normalized_record_urls)
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
