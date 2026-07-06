#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect_notification_reactions as collect  # noqa: E402
import notify_ready_items as notify  # noqa: E402


class DeliveryParsingTest(unittest.TestCase):
    def test_parse_telegram_send_message_extracts_message_id(self) -> None:
        body = b'{"ok": true, "result": {"message_id": 42, "chat": {"id": -1001234}}}'
        delivery = notify.parse_telegram_send_message(body, "-1001234")
        self.assertEqual(delivery, {"channel": "telegram", "chat_id": "-1001234", "message_id": 42})

    def test_parse_telegram_send_message_raises_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            notify.parse_telegram_send_message(b'{"ok": false, "description": "chat not found"}', "-1")

    def test_parse_slack_post_message_extracts_ts(self) -> None:
        body = b'{"ok": true, "channel": "C012AB3CD", "ts": "1712345678.000100"}'
        delivery = notify.parse_slack_post_message(body)
        self.assertEqual(delivery["ts"], "1712345678.000100")
        self.assertEqual(delivery["slack_channel"], "C012AB3CD")
        self.assertEqual(delivery["method"], "bot")

    def test_parse_slack_post_message_raises_on_error(self) -> None:
        with self.assertRaises(RuntimeError):
            notify.parse_slack_post_message(b'{"ok": false, "error": "channel_not_found"}')


class EnvFileTest(unittest.TestCase):
    def test_env_file_round_trip_and_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notify-secrets.env"
            notify.save_env_file({"ION_TELEGRAM_CHAT_ID": "-100123", "ION_EMPTY": ""}, path)
            loaded = notify.load_env_file(path)
            self.assertEqual(loaded, {"ION_TELEGRAM_CHAT_ID": "-100123"})
            merged = notify.merged_env(path)
            self.assertEqual(merged.get("ION_TELEGRAM_CHAT_ID"), "-100123")

    def test_env_file_ignores_comments_and_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notify-secrets.env"
            path.write_text('# comment\nION_SLACK_CHANNEL_ID="C0AB"\n\nbroken line\n', encoding="utf-8")
            self.assertEqual(notify.load_env_file(path), {"ION_SLACK_CHANNEL_ID": "C0AB"})


class LatestDeliveriesTest(unittest.TestCase):
    def test_latest_deliveries_keeps_trackable_ids(self) -> None:
        records = [
            {
                "action": "sent",
                "event_key": "item:translated-review:item-a",
                "title": "文章 A",
                "url": "https://example.test/articles/item-a.html",
                "deliveries": [
                    {"channel": "telegram", "chat_id": "-100123", "message_id": 7},
                    {"channel": "slack", "method": "bot", "slack_channel": "C0AB", "ts": "1712.100"},
                ],
            },
            {"action": "marked-existing", "event_key": "item:translated-review:item-b", "title": "文章 B"},
        ]
        tracked = collect.latest_deliveries(records)
        self.assertEqual(tracked["item:translated-review:item-a"]["telegram"]["message_id"], 7)
        self.assertEqual(tracked["item:translated-review:item-a"]["slack"]["ts"], "1712.100")
        self.assertNotIn("item:translated-review:item-b", tracked)
        msg_map = collect.telegram_message_map(tracked)
        self.assertEqual(msg_map[("-100123", 7)], "item:translated-review:item-a")


class TelegramUpdateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.msg_map = {("-100123", 7): "item:translated-review:item-a"}
        self.state: dict = {"telegram_offset": 0, "events": {}}

    def test_reaction_add_then_remove(self) -> None:
        add = {
            "update_id": 1,
            "message_reaction": {
                "chat": {"id": -100123},
                "message_id": 7,
                "user": {"id": 555},
                "new_reaction": [{"type": "emoji", "emoji": "👍"}],
            },
        }
        self.assertTrue(collect.apply_telegram_update(self.state, self.msg_map, add))
        telegram = self.state["events"]["item:translated-review:item-a"]["telegram"]
        self.assertEqual(telegram["reaction_counts"], {"👍": 1})

        remove = {
            "update_id": 2,
            "message_reaction": {
                "chat": {"id": -100123},
                "message_id": 7,
                "user": {"id": 555},
                "new_reaction": [],
            },
        }
        self.assertTrue(collect.apply_telegram_update(self.state, self.msg_map, remove))
        self.assertEqual(telegram["reaction_counts"], {})

    def test_reply_recorded_once(self) -> None:
        reply = {
            "update_id": 3,
            "message": {
                "message_id": 99,
                "chat": {"id": -100123},
                "from": {"id": 555, "first_name": "Ian"},
                "reply_to_message": {"message_id": 7},
                "text": "這篇很值得讀",
                "date": 1750000000,
            },
        }
        self.assertTrue(collect.apply_telegram_update(self.state, self.msg_map, reply))
        self.assertFalse(collect.apply_telegram_update(self.state, self.msg_map, reply))
        replies = self.state["events"]["item:translated-review:item-a"]["telegram"]["replies"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["from"], "Ian")

    def test_unrelated_update_ignored(self) -> None:
        other = {
            "update_id": 4,
            "message": {"message_id": 5, "chat": {"id": -100999}, "text": "hi"},
        }
        self.assertFalse(collect.apply_telegram_update(self.state, self.msg_map, other))
        self.assertEqual(self.state["events"], {})

    def test_anonymous_reaction_count_overrides(self) -> None:
        update = {
            "update_id": 5,
            "message_reaction_count": {
                "chat": {"id": -100123},
                "message_id": 7,
                "reactions": [{"type": {"type": "emoji", "emoji": "❤️"}, "total_count": 3}],
            },
        }
        self.assertTrue(collect.apply_telegram_update(self.state, self.msg_map, update))
        telegram = self.state["events"]["item:translated-review:item-a"]["telegram"]
        self.assertEqual(telegram["reaction_counts"], {"❤️": 3})


if __name__ == "__main__":
    unittest.main()
