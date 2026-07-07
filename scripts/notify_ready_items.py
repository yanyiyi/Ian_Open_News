#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fulltext_store

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITEMS = ROOT / "database" / "items.jsonl"
DEFAULT_ARTICLES = ROOT / "database" / "articles.jsonl"
DEFAULT_STATE = ROOT / ".cache" / "notified-events.jsonl"
DEFAULT_ENV_FILE = ROOT / ".cache" / "notify-secrets.env"
DEFAULT_AUTO_START_FILE = ROOT / ".cache" / "notify-auto-start.txt"
DEFAULT_READER_BASE_URL = "https://technews.ospo.tw/reader"
DEFAULT_MIN_AGE_MINUTES = 15
DEFAULT_AUTO_MAX_AGE_DAYS = 7

CHANNEL_ENV_KEYS = (
    "ION_SLACK_WEBHOOK_URL",
    "ION_SLACK_BOT_TOKEN",
    "ION_SLACK_CHANNEL_ID",
    "ION_TELEGRAM_BOT_TOKEN",
    "ION_TELEGRAM_CHAT_ID",
    "ION_PUBLIC_BASE_URL",
    "ION_NOTIFY_CHANNELS",
    "ION_NOTIFY_AUTO_START_AT",
)

DEFAULT_ITEM_STATUSES = {
    "triaged",
    "researching",
    "drafting",
    "reviewing",
    "fact-checking",
    "ready",
    "published",
}

TRACK_LABELS = {
    "open-tech-open-industry": "開放科技與開放產業發展",
    "digital-humanities-local-knowledge": "數位人文與在地知識建構",
    "unclassified": "未分類",
}

CONTENT_KIND_LABELS = {
    "featured-article": "可用材料 / 可進編輯台",
    "opinion-article": "觀點文章",
    "small-news": "純新聞 / 小消息",
    "needs-review": "待人工判斷",
}

TRANSLATED_MARKDOWN_KEYS = (
    "codex_translated_article_markdown_zh",
    "translated_article_markdown_zh",
    "claude_translated_article_markdown_zh",
    "gemini_translated_article_markdown_zh",
    "ollama_translated_article_markdown_zh",
    "ollama_gemma4_translated_article_markdown_zh",
    "ollama_twinkle_translated_article_markdown_zh",
)

REVIEW_KEYS = (
    "codex_review",
    "claude_review",
    "gemini_review",
    "ollama_review",
    "ollama_gemma4_review",
    "ollama_twinkle_review",
)

IMAGE_URL_RE = re.compile(r"^https?://.+\.(?:avif|gif|jpe?g|png|svg|webp)(?:[?#].*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class NotificationEvent:
    event_key: str
    kind: str
    record_id: str
    title: str
    text: str
    url: str
    ready_at: str = ""
    image_url: str = ""
    slack_text: str = ""      # Slack mrkdwn 版；空字串時退回 text
    telegram_text: str = ""   # Telegram HTML 版（parse_mode=HTML）；空字串時退回 text


def clean_text(value: object, limit: int = 0) -> str:
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


# ── 移除「給 Ian／值得 Ian／Ian 可以」這類對編輯喊話的字樣 ──────────────────
# 推播不該出現稱呼編輯的字樣；新資料在 codex_enrich_reviews 存檔時已洗過，
# 這裡對送出前的內容再過濾一次，兼顧尚未清理的舊資料。與 local_web 同一套規則。
_EDITOR_ADDRESS_SUBS = [
    (re.compile(r"^\s*給\s*Ian\s*的[^：:。，,\n]{0,16}?[：:]\s*"), ""),
    (re.compile(r"^\s*給\s*Ian\s*的?\s*[：:，,、]?\s*"), ""),
    (re.compile(r"^\s*Ian\s*[：:，,、]\s*"), ""),
    (re.compile(r"留給\s*Ian\s*人工"), "留待人工"),
    (re.compile(r"保留給\s*Ian\s*人工"), "保留待人工"),
    (re.compile(r"給\s*Ian\s*人工"), "待人工"),
    (re.compile(r"值得\s*Ian(?!\s*Open\s+News)\s*"), "值得"),
    (re.compile(r"建議\s*Ian(?!\s*Open\s+News)\s*"), "建議"),
    (re.compile(r"提醒\s*Ian(?!\s*Open\s+News)\s*"), "提醒"),
    (re.compile(r"Ian\s*(?=可以|應該|可先|不妨|得先|要先|需要|建議|值得|不必|別|請)"), ""),
    (re.compile(r"^\s*[（(]\s*Ian\s*[)）]\s*[：:，,、]?\s*"), ""),
]


def strip_editor_address(value: object) -> str:
    """去掉對編輯（Ian）喊話的字樣，只留下判斷本身。"""
    if value is None:
        return ""
    text = str(value)
    for pattern, repl in _EDITOR_ADDRESS_SUBS:
        text = pattern.sub(repl, text)
    text = re.sub(r"^\s*[，,、：:]\s*", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return text


def parse_event_datetime(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00").replace("/", "-")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        match = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", normalized)
        if not match:
            return None
        year, month, day = (int(part) for part in match.groups())
        try:
            parsed = datetime(year, month, day)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def event_age_minutes(event: NotificationEvent, now: datetime | None = None) -> float | None:
    ready_at = parse_event_datetime(event.ready_at)
    if not ready_at:
        return None
    current = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    return (current - ready_at).total_seconds() / 60


def resolve_auto_start_at(
    env: dict[str, str],
    path: Path = DEFAULT_AUTO_START_FILE,
    explicit: object = "",
    initialize: bool = False,
) -> datetime | None:
    text = clean_text(explicit) or clean_text(env.get("ION_NOTIFY_AUTO_START_AT"))
    if not text and path.exists():
        text = clean_text(path.read_text(encoding="utf-8"))
    if not text and initialize:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_text(text + "\n", encoding="utf-8")
    return parse_event_datetime(text)


def filter_events_for_auto_send(
    events: list[NotificationEvent],
    min_age_minutes: int = DEFAULT_MIN_AGE_MINUTES,
    max_age_days: int = DEFAULT_AUTO_MAX_AGE_DAYS,
    now: datetime | None = None,
    auto_start_at: datetime | None = None,
) -> list[NotificationEvent]:
    if min_age_minutes <= 0 and max_age_days <= 0:
        return events
    filtered: list[NotificationEvent] = []
    max_age_minutes = max_age_days * 24 * 60 if max_age_days > 0 else 0
    for event in events:
        ready_at = parse_event_datetime(event.ready_at)
        if auto_start_at and ready_at and ready_at < auto_start_at.astimezone(timezone.utc):
            continue
        age = event_age_minutes(event, now)
        if age is None:
            continue
        if min_age_minutes > 0 and age < min_age_minutes:
            continue
        if max_age_minutes > 0 and age > max_age_minutes:
            continue
        filtered.append(event)
    return filtered


def first_text_value(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = clean_text(record.get(key))
        if value:
            return value
    return ""


def record_ready_at(record: dict[str, Any]) -> str:
    ready_at = first_text_value(
        record,
        (
            "ready_at",
            "published_at",
            "updated_at",
            "reviewed_at",
            "created_at",
            "captured_at",
            "date",
        ),
    )
    if ready_at:
        return ready_at
    for container_key in ("editorial_triage", "reading_metadata", "metadata"):
        container = record.get(container_key)
        if isinstance(container, dict):
            ready_at = first_text_value(container, ("ready_at", "updated_at", "reviewed_at", "created_at"))
            if ready_at:
                return ready_at
    return ""


def clean_image_url(value: object) -> str:
    text = clean_text(value)
    return text if IMAGE_URL_RE.match(text) else ""


def first_image_url(value: object, allow_url_key: bool = False) -> str:
    if isinstance(value, str):
        return clean_image_url(value)
    if isinstance(value, list):
        for item in value:
            found = first_image_url(item, allow_url_key=allow_url_key)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        if allow_url_key:
            found = clean_image_url(value.get("url"))
            if found:
                return found
        priority_keys = (
            "image_url",
            "image",
            "og_image",
            "lead_image_url",
            "cover_image",
            "cover_image_url",
            "thumbnail",
            "thumbnail_url",
        )
        for key in priority_keys:
            if key in value:
                found = first_image_url(value.get(key), allow_url_key=True)
                if found:
                    return found
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                found = first_image_url(nested, allow_url_key=False)
                if found:
                    return found
    return ""


def record_image_url(record: dict[str, Any]) -> str:
    for key in (
        "image_url",
        "image",
        "og_image",
        "lead_image_url",
        "cover_image",
        "cover_image_url",
        "thumbnail",
        "thumbnail_url",
    ):
        found = first_image_url(record.get(key))
        if found:
            return found
    for container_key in ("reading_metadata", "metadata", "page_metadata", "open_graph"):
        container = record.get(container_key)
        if isinstance(container, dict):
            found = first_image_url(container)
            if found:
                return found
    return ""


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """KEY=VALUE 格式的本機密鑰檔（.cache 內、不進 git）；LaunchAgent 啟動時拿不到 shell 環境變數，用這個補。"""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def save_env_file(values: dict[str, str], path: Path = DEFAULT_ENV_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in sorted(values.items()) if clean_text(value)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    path.chmod(0o600)


def merged_env(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    env = load_env_file(path)
    env.update(os.environ)
    return env


def safe_id(value: object, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", clean_text(value) or fallback).strip("-")
    return cleaned or fallback


def markdown_plain(text: object) -> str:
    output: list[str] = []
    in_fence = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"[*_`>#]", "", line)
        output.append(clean_text(line))
    return "\n".join(line for line in output if line)


def first_markdown_paragraph(markdown: object, limit: int = 280) -> str:
    in_fence = False
    for raw_line in str(markdown or "").splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line or re.match(r"^#{1,6}\s+", line):
            continue
        paragraph = markdown_plain(line)
        if paragraph:
            return clean_text(paragraph, limit)
    return ""


def reading_metadata(record: dict[str, Any]) -> dict[str, Any]:
    fulltext_store.hydrate_item(record)
    metadata = record.get("reading_metadata")
    return metadata if isinstance(metadata, dict) else {}


def editorial_triage(record: dict[str, Any]) -> dict[str, Any]:
    editorial = record.get("editorial_triage")
    return editorial if isinstance(editorial, dict) else {}


def translated_markdown(record: dict[str, Any]) -> str:
    metadata = reading_metadata(record)
    for key in TRANSLATED_MARKDOWN_KEYS:
        text = clean_text(metadata.get(key))
        if text:
            return str(metadata.get(key) or "").strip()
    return ""


def item_review(record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    editorial = editorial_triage(record)

    def usable(review: object) -> bool:
        if not isinstance(review, dict):
            return False
        one_line = clean_text(review.get("one_line_recommendation"))
        reasons = review.get("reasons")
        return bool(one_line) and isinstance(reasons, list) and len([r for r in reasons if clean_text(r)]) >= 3

    # 先看使用者在 /items/view 勾選要公開／推播的版本；provider 轉 review_key（ollama-gemma4 -> ollama_gemma4_review）
    preferred = clean_text(editorial.get("preferred_review_provider"))
    if preferred:
        preferred_key = preferred.replace("-", "_") + "_review"
        if preferred_key in REVIEW_KEYS and usable(editorial.get(preferred_key)):
            return preferred_key, editorial[preferred_key]
    for key in REVIEW_KEYS:
        if usable(editorial.get(key)):
            return key, editorial[key]
    return "", {}


def item_title(record: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    metadata = reading_metadata(record)
    editorial = editorial_triage(record)
    review = review or {}
    return (
        clean_text(record.get("editorial_title"), 220)
        or clean_text(metadata.get("editorial_title"), 220)
        or clean_text(review.get("zh_title"), 220)
        or clean_text(editorial.get("zh_title"), 220)
        or clean_text(metadata.get("translated_zh_title"), 220)
        or clean_text(record.get("title"), 220)
        or clean_text(record.get("url"), 220)
        or clean_text(record.get("id"), 220)
        or "未命名項目"
    )


def article_title(article: dict[str, Any]) -> str:
    return (
        clean_text(article.get("title"), 220)
        or clean_text(article.get("id"), 220)
        or "未命名專文"
    )


def item_display_kind(record: dict[str, Any], review: dict[str, Any] | None = None) -> str:
    editorial = editorial_triage(record)
    review = review or {}
    explicit = clean_text(record.get("content_kind") or editorial.get("content_kind") or review.get("content_kind"))
    tags = {clean_text(tag) for tag in record.get("tags", []) if clean_text(tag)}
    decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
    status = clean_text(record.get("status"))
    if explicit in {"opinion", "opinion-article"} or "觀點文章" in tags:
        return "opinion-article"
    if status == "triaged" and decision.get("action") == "accepted-for-editing":
        return "featured-article"
    if status == "ready" and decision.get("action") == "direct-pr-small-news":
        return "small-news"
    if status == "ready":
        return "small-news"
    return explicit or "needs-review"


def item_notification_prefix(kind: str) -> str:
    if kind == "small-news":
        return "【新消息】"
    return "【新議題】"


def event_notification_label(event: NotificationEvent) -> str:
    match = re.match(r"^【([^】]+)】", event.text)
    if match:
        return match.group(1)
    if event.kind == "article":
        return "新專文"
    if event.kind == "item":
        return "新議題"
    return event.kind


def public_reader_article_url(item_id: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/articles/{safe_id(item_id, 'item')}.html"


def public_reader_feature_url(article_id: str, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/features/{safe_id(article_id, 'article')}.html"


def meta_line(record: dict[str, Any], kind: str = "") -> str:
    parts = []
    track = TRACK_LABELS.get(clean_text(record.get("track")), clean_text(record.get("track")))
    if track:
        parts.append(track)
    label = CONTENT_KIND_LABELS.get(kind, kind)
    if label:
        parts.append(label)
    tags = [clean_text(tag) for tag in record.get("tags", []) if clean_text(tag)]
    if tags:
        parts.append("、".join(tags[:5]))
    return " / ".join(parts)


# ── 推播排版 ────────────────────────────────────────────────────────────────
# 一句話（引言區塊帶頭）+ 3 個重點 + AI 摘要 + # 標籤 + 連結。Slack 走 mrkdwn
# （*粗體* 與 > 引言），Telegram 走 HTML（<b> 與 <blockquote>, parse_mode=HTML）；
# 內容跟著使用者在 /items/view 勾選的推薦版本走，送出前所有動態文字都過
# strip_editor_address。段落小標的 emoji 依 item id 穩定輪換，整個 feed 看起來多樣、
# 單筆固定。排版版本由 PUSH_FORMAT 決定。
PUSH_FORMAT = "quote-emoji"  # 引言帶頭 + emoji 小標（見 scratchpad 的 push-format mockup）。

_HASHTAG_SKIP = re.compile(r"RSS|新聞活動|^rss$", re.IGNORECASE)  # 系統／來源類標籤不進 #

# 段落小標 emoji 池：依 item id 穩定挑一顆，讓不同則快訊有不同組合、看起來多樣。
_POINTS_EMOJI = ["🔑", "📍", "✅", "🧩", "🎯", "📊", "🗂️"]
_SUMMARY_EMOJI = ["📝", "📄", "🧾", "📚", "🖋️", "🗒️"]


def _pick_emoji(pool: list[str], seed: str, salt: int) -> str:
    """依 seed（通常是 item id）穩定挑一顆 emoji；不同 salt 讓重點／摘要各自輪換。"""
    basis = sum((seed or "x").encode("utf-8")) + salt
    return pool[basis % len(pool)]


def _tg_escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slack_escape(text: object) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def hashtags_from_tags(tags: object, limit: int = 5) -> list[str]:
    """把項目 tags 轉成 #hashtag：去空白／括號、遇逗號拆開、濾掉系統標籤、去重。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        for piece in re.split(r"[,，、/]", str(raw)):
            piece = piece.strip()
            if not piece or _HASHTAG_SKIP.search(piece):
                continue
            piece = re.sub(r"[（(].*?[)）]", "", piece)
            token = re.sub(r"[^0-9A-Za-z一-鿿_]", "", piece)
            if not token or token.casefold() in seen:
                continue
            seen.add(token.casefold())
            result.append("#" + token)
            if len(result) >= limit:
                return result
    return result


def build_channel_messages(
    prefix: str,
    title: str,
    hook: str,
    reasons: list[str],
    summary: str,
    hashtags: list[str],
    url: str,
    seed: str = "",
) -> tuple[str, str, str]:
    """回傳 (plain, slack_mrkdwn, telegram_html)。plain 供 state 記錄與 --dry-run 預覽。

    排版：標題（粗體）→ 一句話（引言區塊）→ {emoji} 重點（編號）→ {emoji} 摘要
    → # 標籤 → 連結。段落小標 emoji 依 seed 穩定輪換。
    """
    reasons = [reason for reason in (reasons or []) if reason][:3]
    tag_line = " ".join(hashtags) if hashtags else ""
    points_emoji = _pick_emoji(_POINTS_EMOJI, seed or title, 1)
    summary_emoji = _pick_emoji(_SUMMARY_EMOJI, seed or title, 2)

    def assemble(bold, quote, esc) -> str:
        parts = [f"{prefix}{bold(esc(title))}"]
        if hook:
            parts += ["", quote(esc(hook))]
        if reasons:
            parts += ["", f"{points_emoji} {bold('重點')}"] + [
                f"{index}. {esc(reason)}" for index, reason in enumerate(reasons, 1)
            ]
        if summary:
            parts += ["", f"{summary_emoji} {bold('摘要')}", esc(summary)]
        if tag_line:
            parts += ["", esc(tag_line)]
        parts += ["", url]
        return "\n".join(parts)

    plain = assemble(lambda text: text, lambda text: f"「{text}」", lambda text: text)
    slack = assemble(lambda text: f"*{text}*", lambda text: f"> {text}", _slack_escape)
    telegram = assemble(
        lambda text: f"<b>{text}</b>", lambda text: f"<blockquote>{text}</blockquote>", _tg_escape
    )
    return plain, slack, telegram


def article_event(article: dict[str, Any], base_url: str) -> NotificationEvent | None:
    if clean_text(article.get("status")) != "published":
        return None
    article_id = clean_text(article.get("id"))
    if not article_id:
        return None
    title = article_title(article)
    excerpt = strip_editor_address(
        clean_text(article.get("summary"), 360)
        or clean_text(article.get("dek"), 360)
        or first_markdown_paragraph(article.get("body_markdown"), 360)
    )
    url = public_reader_feature_url(article_id, base_url)
    hashtags = hashtags_from_tags(article.get("tags"))
    plain, slack, telegram = build_channel_messages("【新專文】", title, excerpt, [], "", hashtags, url, seed=article_id)
    return NotificationEvent(
        event_key=f"article:published:{article_id}",
        kind="article",
        record_id=article_id,
        title=title,
        text=plain,
        slack_text=slack,
        telegram_text=telegram,
        url=url,
        ready_at=record_ready_at(article),
        image_url=record_image_url(article),
    )


def item_event(record: dict[str, Any], base_url: str, allowed_statuses: set[str], include_needs_fulltext: bool) -> NotificationEvent | None:
    status = clean_text(record.get("status"))
    if status not in allowed_statuses:
        return None
    item_id = clean_text(record.get("id"))
    if not item_id:
        return None
    if not translated_markdown(record):
        return None
    review_key, review = item_review(record)
    if not review_key:
        return None
    if bool(review.get("needs_fulltext")) and not include_needs_fulltext:
        return None

    reasons = [clean_text(strip_editor_address(reason), 220) for reason in review.get("reasons", [])]
    reasons = [reason for reason in reasons if reason]
    if len(reasons) < 3:
        return None
    title = item_title(record, review)
    hook = clean_text(strip_editor_address(review.get("one_line_recommendation")), 360)
    summary = clean_text(strip_editor_address(review.get("summary")), 600)
    prefix = item_notification_prefix(item_display_kind(record, review))
    url = public_reader_article_url(item_id, base_url)
    hashtags = hashtags_from_tags(record.get("tags"))
    plain, slack, telegram = build_channel_messages(prefix, title, hook, reasons[:3], summary, hashtags, url, seed=item_id)
    return NotificationEvent(
        event_key=f"item:translated-review:{item_id}",
        kind="item",
        record_id=item_id,
        title=title,
        text=plain,
        slack_text=slack,
        telegram_text=telegram,
        url=url,
        ready_at=record_ready_at(record),
        image_url=record_image_url(record),
    )


def collect_events(
    articles: list[dict[str, Any]],
    items: list[dict[str, Any]],
    base_url: str,
    allowed_statuses: set[str],
    include_needs_fulltext: bool = False,
    kind: str = "all",
    ids: set[str] | None = None,
) -> list[NotificationEvent]:
    ids = ids or set()
    events: list[NotificationEvent] = []
    if kind in {"all", "articles"}:
        for article in articles:
            if ids and clean_text(article.get("id")) not in ids:
                continue
            event = article_event(article, base_url)
            if event:
                events.append(event)
    if kind in {"all", "items"}:
        for item in items:
            if ids and clean_text(item.get("id")) not in ids:
                continue
            event = item_event(item, base_url, allowed_statuses, include_needs_fulltext)
            if event:
                events.append(event)
    events.sort(key=lambda event: (event.ready_at or "", event.kind, event.title, event.record_id))
    return events


def load_notified_keys(path: Path) -> set[str]:
    return {clean_text(row.get("event_key")) for row in load_jsonl(path) if clean_text(row.get("event_key"))}


def event_state_record(
    event: NotificationEvent,
    channels: list[str],
    action: str,
    deliveries: list[dict[str, Any]] | None = None,
    failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record: dict[str, Any] = {
        "action": action,
        "channels": channels or ["none"],
        "event_key": event.event_key,
        "kind": event.kind,
        "notification_label": event_notification_label(event),
        "record_id": event.record_id,
        "sent_at": now,
        "title": event.title,
        "url": event.url,
    }
    if event.ready_at:
        record["ready_at"] = event.ready_at
    if event.image_url:
        record["image_url"] = event.image_url
    if deliveries:
        record["deliveries"] = deliveries
    if failures:
        record["delivery_failures"] = failures
    return record


def event_state_records(events: list[NotificationEvent], channels: list[str], action: str) -> list[dict[str, Any]]:
    return [event_state_record(event, channels, action) for event in events]


def parse_channels(values: list[str], env: dict[str, str]) -> list[str]:
    raw_values = values[:]
    if not raw_values and env.get("ION_NOTIFY_CHANNELS"):
        raw_values = [env["ION_NOTIFY_CHANNELS"]]
    channels: list[str] = []
    for value in raw_values:
        for part in value.split(","):
            channel = part.strip().lower()
            if channel:
                channels.append(channel)
    if not channels:
        if env.get("ION_SLACK_WEBHOOK_URL") or (env.get("ION_SLACK_BOT_TOKEN") and env.get("ION_SLACK_CHANNEL_ID")):
            channels.append("slack")
        if env.get("ION_TELEGRAM_BOT_TOKEN") and env.get("ION_TELEGRAM_CHAT_ID"):
            channels.append("telegram")
    invalid = sorted(set(channels) - {"slack", "telegram"})
    if invalid:
        raise SystemExit(f"Unsupported channel(s): {', '.join(invalid)}")
    return list(dict.fromkeys(channels))


def post_json(url: str, payload: dict[str, Any], timeout: int, headers: dict[str, str] | None = None) -> bytes:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc)) from exc


def parse_slack_post_message(body: bytes) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Slack chat.postMessage failed: {payload.get('error', 'unknown error')}")
    return {
        "channel": "slack",
        "method": "bot",
        "slack_channel": clean_text(payload.get("channel")),
        "ts": clean_text(payload.get("ts")),
    }


def parse_telegram_send_message(body: bytes, chat_id: str) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram sendMessage failed: {payload.get('description', 'unknown error')}")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    chat = result.get("chat") if isinstance(result.get("chat"), dict) else {}
    return {
        "channel": "telegram",
        "chat_id": clean_text(chat.get("id")) or chat_id,
        "message_id": result.get("message_id"),
    }


def slack_message_payload(event: NotificationEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": event.slack_text or event.text,
        "unfurl_links": True,
        "unfurl_media": True,
    }
    if event.image_url:
        payload["attachments"] = [{"fallback": event.title, "image_url": event.image_url}]
    return payload


def send_slack(event: NotificationEvent, env: dict[str, str], timeout: int) -> dict[str, Any]:
    token = clean_text(env.get("ION_SLACK_BOT_TOKEN"))
    channel_id = clean_text(env.get("ION_SLACK_CHANNEL_ID"))
    if token and channel_id:
        payload = slack_message_payload(event)
        payload["channel"] = channel_id
        body = post_json(
            "https://slack.com/api/chat.postMessage",
            payload,
            timeout,
            headers={"Authorization": f"Bearer {token}"},
        )
        return parse_slack_post_message(body)
    webhook = clean_text(env.get("ION_SLACK_WEBHOOK_URL"))
    if not webhook:
        raise RuntimeError(
            "Set ION_SLACK_WEBHOOK_URL, or ION_SLACK_BOT_TOKEN plus ION_SLACK_CHANNEL_ID for reaction tracking"
        )
    post_json(webhook, slack_message_payload(event), timeout)
    return {"channel": "slack", "method": "webhook"}


def send_telegram(event: NotificationEvent, env: dict[str, str], timeout: int) -> dict[str, Any]:
    token = clean_text(env.get("ION_TELEGRAM_BOT_TOKEN"))
    chat_id = clean_text(env.get("ION_TELEGRAM_CHAT_ID"))
    if not token or not chat_id:
        raise RuntimeError("ION_TELEGRAM_BOT_TOKEN and ION_TELEGRAM_CHAT_ID must both be set")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "disable_web_page_preview": False,
        "text": event.telegram_text or event.text,
    }
    if event.telegram_text:
        payload["parse_mode"] = "HTML"
    body = post_json(url, payload, timeout)
    return parse_telegram_send_message(body, chat_id)


def send_event(
    event: NotificationEvent,
    channels: list[str],
    env: dict[str, str],
    timeout: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    deliveries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for channel in channels:
        try:
            if channel == "slack":
                deliveries.append(send_slack(event, env, timeout))
            elif channel == "telegram":
                deliveries.append(send_telegram(event, env, timeout))
        except RuntimeError as exc:
            failures.append({"channel": channel, "error": clean_text(exc, 1000)})
    return deliveries, failures


def print_event_preview(event: NotificationEvent) -> None:
    print(f"--- {event.event_key}")
    if event.slack_text or event.telegram_text:
        print("[Slack mrkdwn]")
        print(event.slack_text or event.text)
        print("\n[Telegram HTML]")
        print(event.telegram_text or event.text)
    else:
        print(event.text)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Notify Slack and Telegram about newly ready Ian Open News content.")
    parser.add_argument("--items", type=Path, default=DEFAULT_ITEMS)
    parser.add_argument("--articles", type=Path, default=DEFAULT_ARTICLES)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--base-url", default=merged_env().get("ION_PUBLIC_BASE_URL") or DEFAULT_READER_BASE_URL)
    parser.add_argument("--kind", choices=["all", "articles", "items"], default="all")
    parser.add_argument("--status", action="append", default=[], help="Allowed item status. Can be repeated.")
    parser.add_argument("--id", action="append", default=[], help="Only consider a specific article or item id. Can be repeated.")
    parser.add_argument("--channel", action="append", default=[], help="slack, telegram, or comma-separated list. Defaults to configured env vars.")
    parser.add_argument("--include-needs-fulltext", action="store_true", help="Allow item reviews that were generated with needs_fulltext=true.")
    parser.add_argument("--force", action="store_true", help="Ignore notification state and send eligible events again.")
    parser.add_argument("--dry-run", action="store_true", help="Print pending messages without sending or writing state.")
    parser.add_argument("--mark-existing", action="store_true", help="Record eligible events as already handled without sending.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=10)
    parser.add_argument(
        "--min-age-minutes",
        type=int,
        default=DEFAULT_MIN_AGE_MINUTES,
        help="For automatic sends, wait until content has been pending this many minutes. Use 0 to disable.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_AUTO_MAX_AGE_DAYS,
        help="For automatic sends, ignore older backlog beyond this many days. Use 0 to disable.",
    )
    parser.add_argument(
        "--auto-start-at",
        default="",
        help="Only auto-send content ready at or after this timestamp. Defaults to env/file and initializes .cache/notify-auto-start.txt.",
    )
    parser.add_argument("--auto-start-file", type=Path, default=DEFAULT_AUTO_START_FILE)
    args = parser.parse_args()

    env = merged_env()
    channels = parse_channels(args.channel, env)
    allowed_statuses = set(args.status or DEFAULT_ITEM_STATUSES)
    selected_ids = {clean_text(value) for value in args.id if clean_text(value)}
    events = collect_events(
        load_jsonl(args.articles),
        load_jsonl(args.items),
        args.base_url,
        allowed_statuses,
        include_needs_fulltext=args.include_needs_fulltext,
        kind=args.kind,
        ids=selected_ids,
    )
    notified = load_notified_keys(args.state) if not args.force else set()
    pending = [event for event in events if event.event_key not in notified]
    if not selected_ids and not args.mark_existing and not args.force:
        auto_start_at = resolve_auto_start_at(env, args.auto_start_file, args.auto_start_at, initialize=True)
        pending = filter_events_for_auto_send(
            pending,
            args.min_age_minutes,
            args.max_age_days,
            auto_start_at=auto_start_at,
        )
    if args.limit > 0:
        pending = pending[: args.limit]

    if args.dry_run:
        for event in pending:
            print_event_preview(event)
        print(f"eligible={len(events)} pending={len(pending)} dry_run=1")
        return

    if args.mark_existing:
        append_jsonl(args.state, event_state_records(pending, channels, "marked-existing"))
        print(f"eligible={len(events)} marked_existing={len(pending)} state={args.state}")
        return

    if pending and not channels:
        raise SystemExit(
            "No notification channels configured. Set ION_SLACK_WEBHOOK_URL, "
            "or ION_TELEGRAM_BOT_TOKEN plus ION_TELEGRAM_CHAT_ID, or run --dry-run."
        )

    sent = 0
    partial = 0
    failed = 0
    for event in pending:
        deliveries, failures = send_event(event, channels, env, args.timeout)
        for failure in failures:
            print(f"failed: {event.event_key}: {failure['channel']}: {failure['error']}", file=sys.stderr)
        if deliveries:
            action = "sent-partial" if failures else "sent"
            append_jsonl(args.state, [event_state_record(event, channels, action, deliveries, failures)])
            sent += 1
            if failures:
                partial += 1
        else:
            failed += 1
    print(
        f"eligible={len(events)} sent={sent} partial={partial} failed={failed} "
        f"channels={','.join(channels) or 'none'} state={args.state}"
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
