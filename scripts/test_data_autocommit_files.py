#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_web  # noqa: E402


class DataAutocommitFilesTest(unittest.TestCase):
    def test_rejected_items_committed_with_review_events(self) -> None:
        labels = set(local_web.data_autocommit_file_labels())

        self.assertIn("database/items.jsonl", labels)
        self.assertIn("database/rejected-items.jsonl", labels)
        self.assertIn("database/review-events.jsonl", labels)

    def test_data_commit_summary_condenses_status(self) -> None:
        status = "\n".join(
            [
                " M database/items.jsonl",
                " M database/review-events.jsonl",
                "?? database/fulltext/item-abc.json",
                "?? database/fulltext/item-def.json",
                'R  "database/old.jsonl" -> "database/sources.jsonl"',
            ]
        )
        summary = local_web.data_commit_summary(status)
        self.assertEqual(summary, "items、review-events、sources、fulltext×2")

    def test_data_commit_message_keeps_grep_prefix(self) -> None:
        message = local_web.data_commit_message(summary="items、fulltext×2")
        self.assertIn("閱讀資料庫自訂紀錄", message)
        self.assertTrue(message.endswith("（items、fulltext×2）"))
        self.assertNotIn("（）", local_web.data_commit_message())


if __name__ == "__main__":
    unittest.main()
