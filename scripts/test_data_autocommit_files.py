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


if __name__ == "__main__":
    unittest.main()
