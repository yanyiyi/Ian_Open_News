#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fulltext_store
import local_web


class DatabaseIntegrityFulltextTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.items = root / "items.jsonl"
        self.rejected = root / "rejected-items.jsonl"
        self.reviews = root / "review-events.jsonl"
        self.fulltext = root / "fulltext"
        self.fulltext.mkdir()
        self.items.write_text(json.dumps({"id": "item-active"}) + "\n", encoding="utf-8")
        self.rejected.write_text("", encoding="utf-8")
        self.reviews.write_text("", encoding="utf-8")
        self._patchers = [
            patch.object(local_web, "ITEMS", self.items),
            patch.object(local_web, "REJECTED_ITEMS", self.rejected),
            patch.object(local_web, "REVIEW_EVENTS", self.reviews),
            patch.object(fulltext_store, "FULLTEXT_DIR", self.fulltext),
        ]
        for patcher in self._patchers:
            patcher.start()
        fulltext_store._STORE_CACHE.clear()

    def tearDown(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        fulltext_store._STORE_CACHE.clear()
        self._tmp.cleanup()

    def write_sidecar(self, item_id: str) -> Path:
        path = self.fulltext / f"{item_id}.json"
        path.write_text('{"article_markdown":"# Full text"}\n', encoding="utf-8")
        return path

    def test_report_includes_only_orphan_fulltext_sidecars(self) -> None:
        self.write_sidecar("item-active")
        self.write_sidecar("item-orphan")

        report = local_web.database_integrity_report()

        fulltext_issues = [issue for issue in report["issues"] if issue["type"] == "orphan_fulltext"]
        self.assertEqual([issue["id"] for issue in fulltext_issues], ["item-orphan"])

    def test_one_click_fix_removes_orphan_sidecar(self) -> None:
        orphan = self.write_sidecar("item-orphan")
        handler = object.__new__(local_web.Handler)

        result = handler.apply_integrity_fix("orphan_fulltext", "item-orphan", "drop_sidecar")

        self.assertTrue(result["ok"])
        self.assertFalse(orphan.exists())

    def test_one_click_fix_refuses_sidecar_with_matching_item(self) -> None:
        active = self.write_sidecar("item-active")
        handler = object.__new__(local_web.Handler)

        result = handler.apply_integrity_fix("orphan_fulltext", "item-active", "drop_sidecar")

        self.assertFalse(result["ok"])
        self.assertTrue(active.exists())


if __name__ == "__main__":
    unittest.main()
