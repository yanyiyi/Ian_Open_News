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
DEFAULT_READER_BASE_URL = "https://technews.ospo.tw/reader"

CHANNEL_ENV_KEYS = (
    "ION_SLACK_WEBHOOK_URL",
    "ION_SLACK_BOT_TOKEN",
    "ION_SLACK_CHANNEL_ID",
    "ION_TELEGRAM_BOT_TOKEN",
    "ION_TELEGRAM_CHAT_ID",
    "ION_PUBLIC_BASE_URL",
    "ION_NOTIFY_CHANNELS",
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


@dataclass(frozen=True)
class NotificationEvent:
    event_key: str
    kind: str
    record_id: str
    title: str
    text: str
    url: str


def clean_text(value: object, limit: int = 0) -> str:
    text = " ".join(str(value or "").split())
    if limit and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


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
    for key in REVIEW_KEYS:
        review = editorial.get(key)
        if isinstance(review, dict):
            one_line = clean_text(review.get("one_line_recommendation"))
            reasons = review.get("reasons")
            if one_line and isinstance(reasons, list) and len([r for r in reasons if clean_text(r)]) >= 3:
                return key, review
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


def article_event(article: dict[str, Any], base_url: str) -> NotificationEvent | None:
    if clean_text(article.get("status")) != "published":
        return None
    article_id = clean_text(article.get("id"))
    if not article_id:
        return None
    title = article_title(article)
    excerpt = (
        clean_text(article.get("summary"), 360)
        or clean_text(article.get("dek"), 360)
        or first_markdown_paragraph(article.get("body_markdown"), 360)
    )
    url = public_reader_feature_url(article_id, base_url)
    pieces = [f"Ian Open News 新專文：{title}"]
    if excerpt:
        pieces.extend(["", excerpt])
    meta = meta_line(article)
    if meta:
        pieces.extend(["", meta])
    pieces.extend(["", url])
    return NotificationEvent(
        event_key=f"article:published:{article_id}",
        kind="article",
        record_id=article_id,
        title=title,
        text="\n".join(pieces),
        url=url,
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

    reasons = [clean_text(reason, 220) for reason in review.get("reasons", []) if clean_text(reason)]
    if len(reasons) < 3:
        return None
    title = item_title(record, review)
    one_line = clean_text(review.get("one_line_recommendation"), 360)
    kind = item_display_kind(record, review)
    url = public_reader_article_url(item_id, base_url)
    pieces = [
        f"Ian Open News 推薦閱讀：{title}",
        "",
        one_line,
        "",
        "值得讀的 3 個理由：",
        f"1. {reasons[0]}",
        f"2. {reasons[1]}",
        f"3. {reasons[2]}",
    ]
    meta = meta_line(record, kind)
    if meta:
        pieces.extend(["", meta])
    pieces.extend(["", url])
    return NotificationEvent(
        event_key=f"item:translated-review:{item_id}",
        kind="item",
        record_id=item_id,
        title=title,
        text="\n".join(pieces),
        url=url,
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
    events.sort(key=lambda event: (event.kind, event.title, event.record_id))
    return events


def load_notified_keys(path: Path) -> set[str]:
    return {clean_text(row.get("event_key")) for row in load_jsonl(path) if clean_text(row.get("event_key"))}


def event_state_record(
    event: NotificationEvent,
    channels: list[str],
    action: str,
    deliveries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record: dict[str, Any] = {
        "action": action,
        "channels": channels or ["none"],
        "event_key": event.event_key,
        "kind": event.kind,
        "record_id": event.record_id,
        "sent_at": now,
        "title": event.title,
        "url": event.url,
    }
    if deliveries:
        record["deliveries"] = deliveries
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


def send_slack(event: NotificationEvent, env: dict[str, str], timeout: int) -> dict[str, Any]:
    token = clean_text(env.get("ION_SLACK_BOT_TOKEN"))
    channel_id = clean_text(env.get("ION_SLACK_CHANNEL_ID"))
    if token and channel_id:
        body = post_json(
            "https://slack.com/api/chat.postMessage",
            {"channel": channel_id, "text": event.text},
            timeout,
            headers={"Authorization": f"Bearer {token}"},
        )
        return parse_slack_post_message(body)
    webhook = clean_text(env.get("ION_SLACK_WEBHOOK_URL"))
    if not webhook:
        raise RuntimeError(
            "Set ION_SLACK_WEBHOOK_URL, or ION_SLACK_BOT_TOKEN plus ION_SLACK_CHANNEL_ID for reaction tracking"
        )
    post_json(webhook, {"text": event.text}, timeout)
    return {"channel": "slack", "method": "webhook"}


def send_telegram(event: NotificationEvent, env: dict[str, str], timeout: int) -> dict[str, Any]:
    token = clean_text(env.get("ION_TELEGRAM_BOT_TOKEN"))
    chat_id = clean_text(env.get("ION_TELEGRAM_CHAT_ID"))
    if not token or not chat_id:
        raise RuntimeError("ION_TELEGRAM_BOT_TOKEN and ION_TELEGRAM_CHAT_ID must both be set")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = post_json(
        url,
        {
            "chat_id": chat_id,
            "disable_web_page_preview": False,
            "text": event.text,
        },
        timeout,
    )
    return parse_telegram_send_message(body, chat_id)


def send_event(event: NotificationEvent, channels: list[str], env: dict[str, str], timeout: int) -> list[dict[str, Any]]:
    deliveries: list[dict[str, Any]] = []
    for channel in channels:
        if channel == "slack":
            deliveries.append(send_slack(event, env, timeout))
        elif channel == "telegram":
            deliveries.append(send_telegram(event, env, timeout))
    return deliveries


def print_event_preview(event: NotificationEvent) -> None:
    print(f"--- {event.event_key}")
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
    for event in pending:
        try:
            deliveries = send_event(event, channels, env, args.timeout)
        except RuntimeError as exc:
            print(f"failed: {event.event_key}: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        append_jsonl(args.state, [event_state_record(event, channels, "sent", deliveries)])
        sent += 1
    print(f"eligible={len(events)} sent={sent} channels={','.join(channels) or 'none'} state={args.state}")


if __name__ == "__main__":
    main()
