#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
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
                "published_at": "2026-07-06T09:30:00+08:00",
                "image_url": "https://example.test/cover.jpg",
            },
            "https://example.test/reader",
        )

        self.assertIsNotNone(event)
        assert event is not None
        self.assertEqual(event.event_key, "article:published:art-test")
        self.assertIn("【新專文】我的專文", event.text)
        self.assertIn("這是文章導言，適合作為摘要。", event.text)
        self.assertIn("https://example.test/reader/features/art-test.html", event.text)
        self.assertNotIn("開放科技與開放產業發展", event.text)
        self.assertEqual(event.ready_at, "2026-07-06T09:30:00+08:00")
        self.assertEqual(event.image_url, "https://example.test/cover.jpg")

    def test_item_event_includes_one_line_reasons_summary_and_hashtags(self) -> None:
        event = notify.item_event(
            {
                "id": "item-test",
                "status": "ready",
                "title": "Original Title",
                "track": "digital-humanities-local-knowledge",
                "tags": ["公共資料", "Open Data", "rss"],
                "reading_metadata": {
                    "translated_article_markdown_zh": "# 中文全文\n\n第一段。",
                },
                "editorial_triage": {
                    "codex_review": {
                        "zh_title": "中文標題",
                        "one_line_recommendation": "給 Ian：這篇適合讀，因為它提供公共資料治理切角。",
                        "reasons": [
                            "第一個理由。",
                            "第二個理由。",
                            "第三個理由。",
                        ],
                        "summary": "這段摘要現在應該進通知，幫讀者導讀。",
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
        # 一句話 + 3 個重點 + 摘要三段都在
        self.assertIn("【新消息】中文標題", event.text)
        self.assertIn("這篇適合讀", event.text)
        self.assertIn("1. 第一個理由。", event.text)
        self.assertIn("3. 第三個理由。", event.text)
        self.assertIn("這段摘要現在應該進通知", event.text)  # 摘要現在會進推播
        # 標籤轉 #，系統標籤 rss 被濾掉
        self.assertIn("#公共資料", event.text)
        self.assertIn("#OpenData", event.text)
        self.assertNotIn("#rss", event.text)
        # 「給 Ian」在任何頻道都不出現
        self.assertNotIn("給 Ian", event.text)
        self.assertNotIn("給 Ian", event.slack_text)
        self.assertNotIn("給 Ian", event.telegram_text)
        # 頻道排版：Slack 用 *粗體*、Telegram 用 <b>，兩者不同
        self.assertIn("*重點*", event.slack_text)
        self.assertIn("<b>重點</b>", event.telegram_text)
        self.assertNotEqual(event.slack_text, event.telegram_text)
        self.assertNotIn("數位人文與在地知識建構", event.text)

    def test_strip_editor_address_preserves_real_person_names(self) -> None:
        self.assertEqual(
            notify.strip_editor_address("英國部長 Ian Murray 出席會議。"),
            "英國部長 Ian Murray 出席會議。",
        )
        self.assertEqual(
            notify.strip_editor_address("值得 Ian 先收，這是數位公共服務 AI 治理案例。"),
            "值得先收，這是數位公共服務 AI 治理案例。",
        )
        self.assertEqual(
            notify.strip_editor_address("不值得 Ian Open News 優先處理。"),
            "不值得 Ian Open News 優先處理。",
        )

    def test_item_event_honours_preferred_review_provider(self) -> None:
        item = {
            "id": "item-pref",
            "status": "ready",
            "reading_metadata": {"translated_article_markdown_zh": "# 中文全文\n\n第一段。"},
            "editorial_triage": {
                "preferred_review_provider": "gemini",
                "codex_review": {
                    "zh_title": "Codex 版",
                    "one_line_recommendation": "Codex 的一句話。",
                    "reasons": ["一", "二", "三"],
                    "needs_fulltext": False,
                },
                "gemini_review": {
                    "zh_title": "Gemini 版",
                    "one_line_recommendation": "Gemini 的一句話。",
                    "reasons": ["甲", "乙", "丙"],
                    "needs_fulltext": False,
                },
            },
        }
        event = notify.item_event(
            item, "https://example.test/reader", notify.DEFAULT_ITEM_STATUSES, include_needs_fulltext=False
        )
        self.assertIsNotNone(event)
        assert event is not None
        self.assertIn("Gemini 的一句話。", event.text)
        self.assertIn("甲", event.text)
        self.assertNotIn("Codex 的一句話。", event.text)

    def test_triaged_material_event_uses_new_issue_prefix(self) -> None:
        event = notify.item_event(
            {
                "id": "item-issue",
                "status": "triaged",
                "local_decision": {"action": "accepted-for-editing"},
                "reading_metadata": {
                    "translated_article_markdown_zh": "# 中文全文\n\n第一段。",
                    "og_image": "https://example.test/issue.png",
                },
                "editorial_triage": {
                    "codex_review": {
                        "zh_title": "材料庫題目",
                        "one_line_recommendation": "這篇可以收進材料庫。",
                        "reasons": ["一", "二", "三"],
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
        self.assertIn("【新議題】材料庫題目", event.text)
        self.assertEqual(event.image_url, "https://example.test/issue.png")

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

    def test_auto_send_filter_waits_and_skips_old_backlog(self) -> None:
        now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
        waiting = notify.NotificationEvent(
            "item:waiting",
            "item",
            "waiting",
            "Waiting",
            "Message",
            "https://example.test/waiting",
            ready_at=(now - timedelta(minutes=10)).isoformat(),
        )
        ready = notify.NotificationEvent(
            "item:ready",
            "item",
            "ready",
            "Ready",
            "Message",
            "https://example.test/ready",
            ready_at=(now - timedelta(minutes=20)).isoformat(),
        )
        old = notify.NotificationEvent(
            "item:old",
            "item",
            "old",
            "Old",
            "Message",
            "https://example.test/old",
            ready_at=(now - timedelta(days=9)).isoformat(),
        )

        filtered = notify.filter_events_for_auto_send([waiting, ready, old], now=now)

        self.assertEqual(filtered, [ready])

    def test_auto_send_filter_skips_events_before_auto_start(self) -> None:
        now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
        auto_start = now - timedelta(minutes=30)
        before_start = notify.NotificationEvent(
            "item:before-start",
            "item",
            "before-start",
            "Before",
            "Message",
            "https://example.test/before",
            ready_at=(now - timedelta(minutes=40)).isoformat(),
        )
        after_start = notify.NotificationEvent(
            "item:after-start",
            "item",
            "after-start",
            "After",
            "Message",
            "https://example.test/after",
            ready_at=(now - timedelta(minutes=20)).isoformat(),
        )

        filtered = notify.filter_events_for_auto_send([before_start, after_start], now=now, auto_start_at=auto_start)

        self.assertEqual(filtered, [after_start])

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
