#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fulltext_store  # noqa: E402
import notify_ready_items as notify  # noqa: E402


class NotifyReadyItemsTest(unittest.TestCase):
    def test_published_article_event_uses_article_excerpt(self) -> None:
        event = notify.article_event(
            {
                "id": "art-test",
                "status": "published",
                "title": "我的專文",
                "body_markdown": "# 我的專文\n\n這是文章導言，適合作為摘要。\n\n第二段。",
                "track": "open-tech-open-industry",
                "tags": ["開放資料"],
            },
            "https://example.test/reader",
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.event_key, "article:published:art-test")
        self.assertIn("Ian Open News 新專文：我的專文", event.text)
        self.assertIn("這是文章導言，適合作為摘要。", event.text)
        self.assertIn("https://example.test/reader/features/art-test.html", event.text)
        self.assertNotIn("開放科技與開放產業發展", event.text)

    def test_item_event_uses_one_line_and_three_reasons_instead_of_summary(self) -> None:
        event = notify.item_event(
            {
                "id": "item-test",
                "status": "ready",
                "title": "Original Title",
                "track": "digital-humanities-local-knowledge",
                "reading_metadata": {
                    "translated_article_markdown_zh": "# 中文全文\n\n第一段。",
                },
                "editorial_triage": {
                    "codex_review": {
                        "zh_title": "中文標題",
                        "one_line_recommendation": "這篇適合讀，因為它提供公共資料治理切角。",
                        "reasons": [
                            "第一個理由。",
                            "第二個理由。",
                            "第三個理由。",
                        ],
                        "summary": "這段摘要不應該成為通知主體。",
                        "needs_fulltext": False,
                    }
                },
            },
            "https://example.test/reader",
            notify.DEFAULT_ITEM_STATUSES,
            include_needs_fulltext=False,
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.event_key, "item:translated-review:item-test")
        self.assertIn("Ian Open News 推薦閱讀：中文標題", event.text)
        self.assertIn("這篇適合讀", event.text)
        self.assertIn("1. 第一個理由。", event.text)
        self.assertIn("2. 第二個理由。", event.text)
        self.assertIn("3. 第三個理由。", event.text)
        self.assertNotIn("這段摘要不應該成為通知主體", event.text)
        self.assertNotIn("數位人文與在地知識建構", event.text)
        self.assertNotIn("純新聞 / 小消息", event.text)

    def test_item_event_skips_reviews_that_still_need_fulltext_by_default(self) -> None:
        item = {
            "id": "item-needs-fulltext",
            "status": "ready",
            "reading_metadata": {"translated_article_markdown_zh": "# 中文全文\n\n第一段。"},
            "editorial_triage": {
                "codex_review": {
                    "one_line_recommendation": "一句話。",
                    "reasons": ["一", "二", "三"],
                    "needs_fulltext": True,
                }
            },
        }

        skipped = notify.item_event(
            item,
            "https://example.test/reader",
            notify.DEFAULT_ITEM_STATUSES,
            include_needs_fulltext=False,
        )
        included = notify.item_event(
            item,
            "https://example.test/reader",
            notify.DEFAULT_ITEM_STATUSES,
            include_needs_fulltext=True,
        )

        self.assertIsNone(skipped)
        self.assertIsNotNone(included)

    def test_notified_state_filters_pending_events(self) -> None:
        event = notify.NotificationEvent(
            event_key="item:translated-review:item-a",
            kind="item",
            record_id="item-a",
            title="Title",
            text="Message",
            url="https://example.test/reader/articles/item-a.html",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "notified-events.jsonl"
            notify.append_jsonl(state, notify.event_state_records([event], ["slack"], "sent"))

            self.assertEqual(notify.load_notified_keys(state), {"item:translated-review:item-a"})

    def test_parse_channels_accepts_slack_bot_without_webhook(self) -> None:
        channels = notify.parse_channels(
            [],
            {"ION_SLACK_BOT_TOKEN": "xoxb-test", "ION_SLACK_CHANNEL_ID": "C123"},
        )

        self.assertEqual(channels, ["slack"])

    def test_item_event_hydrates_translation_from_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_dir = fulltext_store.FULLTEXT_DIR
            fulltext_store.FULLTEXT_DIR = Path(tmpdir)
            fulltext_store._STORE_CACHE.clear()
            try:
                item = {
                    "id": "item-sidecar",
                    "status": "ready",
                    "title": "Original Title",
                    "track": "open-tech-open-industry",
                    "reading_metadata": {},
                    "editorial_triage": {
                        "codex_review": {
                            "zh_title": "中文標題",
                            "one_line_recommendation": "值得讀。",
                            "reasons": ["一", "二", "三"],
                            "needs_fulltext": False,
                        }
                    },
                }
                fulltext_store.dehydrate_item(
                    {
                        "id": "item-sidecar",
                        "reading_metadata": {"codex_translated_article_markdown_zh": "# 中文全文"},
                    }
                )

                event = notify.item_event(
                    item,
                    "https://example.test/reader",
                    notify.DEFAULT_ITEM_STATUSES,
                    include_needs_fulltext=False,
                )
            finally:
                fulltext_store.FULLTEXT_DIR = original_dir
                fulltext_store._STORE_CACHE.clear()

        self.assertIsNotNone(event)

    def test_send_event_collects_channel_failures_without_stopping(self) -> None:
        event = notify.NotificationEvent(
            event_key="article:published:art-test",
            kind="article",
            record_id="art-test",
            title="Title",
            text="Message",
            url="https://example.test/reader/features/art-test.html",
        )

        with (
            mock.patch.object(notify, "send_slack", side_effect=RuntimeError("Slack chat.postMessage failed: not_in_channel")),
            mock.patch.object(notify, "send_telegram", return_value={"channel": "telegram", "message_id": 123}),
        ):
            deliveries, failures = notify.send_event(event, ["slack", "telegram"], {}, 10)

        self.assertEqual(deliveries, [{"channel": "telegram", "message_id": 123}])
        self.assertEqual(failures, [{"channel": "slack", "error": "Slack chat.postMessage failed: not_in_channel"}])

    def test_event_state_record_can_store_delivery_failures(self) -> None:
        event = notify.NotificationEvent(
            event_key="article:published:art-test",
            kind="article",
            record_id="art-test",
            title="Title",
            text="Message",
            url="https://example.test/reader/features/art-test.html",
        )

        record = notify.event_state_record(
            event,
            ["slack", "telegram"],
            "sent-partial",
            [{"channel": "telegram", "message_id": 123}],
            [{"channel": "slack", "error": "not_in_channel"}],
        )

        self.assertEqual(record["action"], "sent-partial")
        self.assertEqual(record["deliveries"], [{"channel": "telegram", "message_id": 123}])
        self.assertEqual(record["delivery_failures"], [{"channel": "slack", "error": "not_in_channel"}])


if __name__ == "__main__":
    unittest.main()
