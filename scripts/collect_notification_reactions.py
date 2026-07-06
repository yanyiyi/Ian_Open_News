#!/usr/bin/env python3
"""Collect emoji reactions and replies for previously sent notifications.

Reads `.cache/notified-events.jsonl` (written by notify_ready_items.py) to know
which Slack/Telegram messages belong to which event, then:

- Telegram: polls getUpdates for message_reaction / message_reaction_count /
  reply messages. The bot must be a member of the chat; for group reaction
  updates Telegram requires the bot to be an administrator.
- Slack: needs ION_SLACK_BOT_TOKEN (the same one used by notify_ready_items in
  bot mode) with reactions:read + channels:history scopes. Webhook-only
  deliveries carry no message ts, so they cannot be tracked.

Aggregated results are written to `.cache/notification-reactions.json`.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from notify_ready_items import clean_text, load_jsonl, merged_env, post_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / ".cache" / "notified-events.jsonl"
DEFAULT_OUTPUT = ROOT / ".cache" / "notification-reactions.json"
REPLY_TEXT_LIMIT = 280
MAX_REPLIES_PER_EVENT = 50


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_json(url: str, timeout: int, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc)) from exc


def load_state(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("events", {})
                return data
        except json.JSONDecodeError:
            pass
    return {"telegram_offset": 0, "events": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def latest_deliveries(notified_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """event_key -> {title, url, telegram: {chat_id, message_id}, slack: {slack_channel, ts}}"""
    tracked: dict[str, dict[str, Any]] = {}
    for record in notified_records:
        event_key = clean_text(record.get("event_key"))
        if not event_key or record.get("action") != "sent":
            continue
        entry = tracked.setdefault(
            event_key,
            {"title": clean_text(record.get("title")), "url": clean_text(record.get("url"))},
        )
        for delivery in record.get("deliveries", []) or []:
            if not isinstance(delivery, dict):
                continue
            if delivery.get("channel") == "telegram" and delivery.get("message_id"):
                entry["telegram"] = {
                    "chat_id": clean_text(delivery.get("chat_id")),
                    "message_id": delivery.get("message_id"),
                }
            elif delivery.get("channel") == "slack" and clean_text(delivery.get("ts")):
                entry["slack"] = {
                    "slack_channel": clean_text(delivery.get("slack_channel")),
                    "ts": clean_text(delivery.get("ts")),
                }
    return tracked


def telegram_message_map(tracked: dict[str, dict[str, Any]]) -> dict[tuple[str, int], str]:
    mapping: dict[tuple[str, int], str] = {}
    for event_key, entry in tracked.items():
        telegram = entry.get("telegram") or {}
        chat_id = clean_text(telegram.get("chat_id"))
        message_id = telegram.get("message_id")
        if chat_id and isinstance(message_id, int):
            mapping[(chat_id, message_id)] = event_key
    return mapping


def reaction_emoji(reaction: dict[str, Any]) -> str:
    if reaction.get("type") == "emoji":
        return clean_text(reaction.get("emoji"))
    if reaction.get("type") == "custom_emoji":
        return f"custom:{clean_text(reaction.get('custom_emoji_id'))}"
    if reaction.get("type") == "paid":
        return "⭐paid"
    return ""


def event_channel_state(state: dict[str, Any], event_key: str, channel: str) -> dict[str, Any]:
    events = state.setdefault("events", {})
    event_state = events.setdefault(event_key, {})
    return event_state.setdefault(channel, {})


def apply_telegram_update(state: dict[str, Any], msg_map: dict[tuple[str, int], str], update: dict[str, Any]) -> bool:
    """Apply one getUpdates entry to state. Returns True if anything changed."""
    reaction = update.get("message_reaction")
    if isinstance(reaction, dict):
        chat = reaction.get("chat") if isinstance(reaction.get("chat"), dict) else {}
        key = (clean_text(chat.get("id")), reaction.get("message_id"))
        event_key = msg_map.get(key)
        if not event_key:
            return False
        channel_state = event_channel_state(state, event_key, "telegram")
        user = reaction.get("user") if isinstance(reaction.get("user"), dict) else {}
        actor = reaction.get("actor_chat") if isinstance(reaction.get("actor_chat"), dict) else {}
        user_id = clean_text(user.get("id")) or f"chat:{clean_text(actor.get('id'))}"
        emojis = [emoji for emoji in (reaction_emoji(r) for r in reaction.get("new_reaction", []) if isinstance(r, dict)) if emoji]
        by_user = channel_state.setdefault("reactions_by_user", {})
        if emojis:
            by_user[user_id] = emojis
        else:
            by_user.pop(user_id, None)
        counts: dict[str, int] = {}
        for user_emojis in by_user.values():
            for emoji in user_emojis:
                counts[emoji] = counts.get(emoji, 0) + 1
        channel_state["reaction_counts"] = counts
        return True

    reaction_count = update.get("message_reaction_count")
    if isinstance(reaction_count, dict):
        chat = reaction_count.get("chat") if isinstance(reaction_count.get("chat"), dict) else {}
        key = (clean_text(chat.get("id")), reaction_count.get("message_id"))
        event_key = msg_map.get(key)
        if not event_key:
            return False
        counts = {}
        for entry in reaction_count.get("reactions", []) or []:
            if not isinstance(entry, dict):
                continue
            emoji = reaction_emoji(entry.get("type") if isinstance(entry.get("type"), dict) else {})
            total = entry.get("total_count")
            if emoji and isinstance(total, int):
                counts[emoji] = total
        event_channel_state(state, event_key, "telegram")["reaction_counts"] = counts
        return True

    message = update.get("message")
    if isinstance(message, dict):
        reply_to = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        key = (clean_text(chat.get("id")), reply_to.get("message_id"))
        event_key = msg_map.get(key)
        if not event_key:
            return False
        channel_state = event_channel_state(state, event_key, "telegram")
        replies = channel_state.setdefault("replies", [])
        reply_id = message.get("message_id")
        if any(reply.get("message_id") == reply_id for reply in replies):
            return False
        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        replies.append(
            {
                "message_id": reply_id,
                "from": clean_text(sender.get("username") or sender.get("first_name") or sender.get("id")),
                "text": clean_text(message.get("text") or message.get("caption"), REPLY_TEXT_LIMIT),
                "date": message.get("date"),
            }
        )
        del replies[:-MAX_REPLIES_PER_EVENT]
        return True
    return False


def collect_telegram(state: dict[str, Any], msg_map: dict[tuple[str, int], str], env: dict[str, str], timeout: int) -> int:
    token = clean_text(env.get("ION_TELEGRAM_BOT_TOKEN"))
    if not token or not msg_map:
        return 0
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    changed = 0
    while True:
        payload = {
            "offset": int(state.get("telegram_offset") or 0),
            "timeout": 0,
            "allowed_updates": ["message", "message_reaction", "message_reaction_count"],
        }
        body = post_json(url, payload, timeout)
        response = json.loads(body.decode("utf-8"))
        if not response.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {response.get('description', 'unknown error')}")
        updates = response.get("result") or []
        if not updates:
            break
        for update in updates:
            if apply_telegram_update(state, msg_map, update):
                changed += 1
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                state["telegram_offset"] = max(int(state.get("telegram_offset") or 0), update_id + 1)
        if len(updates) < 100:
            break
    return changed


def collect_slack(state: dict[str, Any], tracked: dict[str, dict[str, Any]], env: dict[str, str], timeout: int) -> int:
    token = clean_text(env.get("ION_SLACK_BOT_TOKEN"))
    if not token:
        return 0
    headers = {"Authorization": f"Bearer {token}"}
    changed = 0
    for event_key, entry in tracked.items():
        slack = entry.get("slack") or {}
        channel_id = clean_text(slack.get("slack_channel"))
        ts = clean_text(slack.get("ts"))
        if not channel_id or not ts:
            continue
        query = urllib.parse.urlencode({"channel": channel_id, "timestamp": ts})
        reactions_response = get_json(f"https://slack.com/api/reactions.get?{query}", timeout, headers)
        if not reactions_response.get("ok"):
            print(f"slack reactions.get failed for {event_key}: {reactions_response.get('error')}", file=sys.stderr)
            continue
        message = reactions_response.get("message") if isinstance(reactions_response.get("message"), dict) else {}
        counts = {
            clean_text(reaction.get("name")): reaction.get("count", 0)
            for reaction in message.get("reactions", []) or []
            if isinstance(reaction, dict) and clean_text(reaction.get("name"))
        }
        channel_state = event_channel_state(state, event_key, "slack")
        channel_state["reaction_counts"] = counts

        replies_query = urllib.parse.urlencode({"channel": channel_id, "ts": ts, "limit": MAX_REPLIES_PER_EVENT + 1})
        replies_response = get_json(f"https://slack.com/api/conversations.replies?{replies_query}", timeout, headers)
        if replies_response.get("ok"):
            messages = [msg for msg in replies_response.get("messages", []) or [] if isinstance(msg, dict)]
            replies = [
                {
                    "ts": clean_text(msg.get("ts")),
                    "from": clean_text(msg.get("user") or msg.get("username")),
                    "text": clean_text(msg.get("text"), REPLY_TEXT_LIMIT),
                }
                for msg in messages
                if clean_text(msg.get("ts")) != ts
            ]
            channel_state["replies"] = replies[:MAX_REPLIES_PER_EVENT]
        changed += 1
    return changed


def stamp_events(state: dict[str, Any], tracked: dict[str, dict[str, Any]]) -> None:
    now = utc_now()
    for event_key, entry in tracked.items():
        event_state = state.setdefault("events", {}).setdefault(event_key, {})
        event_state["title"] = entry.get("title") or event_state.get("title") or ""
        event_state["url"] = entry.get("url") or event_state.get("url") or ""
        event_state["updated_at"] = now


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Slack/Telegram reactions and replies for sent notifications.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="notified-events.jsonl written by notify_ready_items.py")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="aggregated reactions JSON")
    parser.add_argument("--skip-telegram", action="store_true")
    parser.add_argument("--skip-slack", action="store_true")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    env = merged_env()
    tracked = latest_deliveries(load_jsonl(args.state))
    state = load_state(args.output)

    telegram_changed = 0
    slack_changed = 0
    if not args.skip_telegram:
        telegram_changed = collect_telegram(state, telegram_message_map(tracked), env, args.timeout)
    if not args.skip_slack:
        slack_changed = collect_slack(state, tracked, env, args.timeout)

    stamp_events(state, tracked)
    save_state(args.output, state)
    trackable = sum(1 for entry in tracked.values() if entry.get("telegram") or entry.get("slack"))
    print(
        f"tracked={len(tracked)} trackable={trackable} "
        f"telegram_updates={telegram_changed} slack_messages={slack_changed} output={args.output}"
    )


if __name__ == "__main__":
    main()
