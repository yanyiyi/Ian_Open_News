#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fulltext_store
import validate_database


class ValidateDatabaseFulltextTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = fulltext_store.FULLTEXT_DIR
        fulltext_store.FULLTEXT_DIR = Path(self._tmp.name)
        fulltext_store._STORE_CACHE.clear()

    def tearDown(self) -> None:
        fulltext_store.FULLTEXT_DIR = self._orig_dir
        fulltext_store._STORE_CACHE.clear()
        self._tmp.cleanup()

    def write_sidecar(self, name: str, text: str) -> None:
        path = fulltext_store.FULLTEXT_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_valid_sidecar_for_existing_item_passes(self) -> None:
        self.write_sidecar("item-a.json", '{"article_markdown":"# Full text"}')
        errors = validate_database.validate_fulltext_sidecars(
            [{"id": "item-a", "_line": 1, "reading_metadata": {}}],
            [],
            Path("items.jsonl"),
            Path("rejected-items.jsonl"),
        )

        self.assertEqual(errors, [])

    def test_orphan_and_non_fulltext_keys_fail(self) -> None:
        self.write_sidecar("item-a.json", '{"not_fulltext":"x"}')
        self.write_sidecar("item-orphan.json", '{"article_markdown":"# Full text"}')
        errors = validate_database.validate_fulltext_sidecars(
            [{"id": "item-a", "_line": 1, "reading_metadata": {}}],
            [],
            Path("items.jsonl"),
            Path("rejected-items.jsonl"),
        )

        self.assertTrue(any("not a fulltext field" in error for error in errors))
        self.assertTrue(any("no matching item id" in error for error in errors))

    def test_inline_conflict_fails(self) -> None:
        self.write_sidecar("item-a.json", '{"article_markdown":"# Store"}')
        errors = validate_database.validate_fulltext_sidecars(
            [{"id": "item-a", "_line": 7, "reading_metadata": {"article_markdown": "# Inline"}}],
            [],
            Path("items.jsonl"),
            Path("rejected-items.jsonl"),
        )

        self.assertTrue(any("differs from inline" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
