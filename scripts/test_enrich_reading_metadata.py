#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import enrich_reading_metadata
import page_metadata


class ReadingMetadataRulesTest(unittest.TestCase):
    def test_missing_reader_fields_checks_all_three_fields(self) -> None:
        item = {
            "summary": "",
            "reference": {"raw_columns": {"圖片": "https://example.com/cover.jpg"}},
            "reading_metadata": {
                "description": "Page description",
                "article_markdown": "# Article\n\nBody",
            },
        }
        self.assertEqual(enrich_reading_metadata.missing_reader_fields(item), [])
        self.assertEqual(
            enrich_reading_metadata.missing_reader_fields({"reading_metadata": {}}),
            ["image", "description", "article"],
        )

    def test_retry_cooldown_uses_last_attempt(self) -> None:
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        item = {
            "reading_metadata": {
                "reader_enrichment": {"last_attempt_at": "2026-06-24T00:00:00+00:00"}
            }
        }
        self.assertFalse(enrich_reading_metadata.retry_is_due(item, now, 7))
        self.assertTrue(enrich_reading_metadata.retry_is_due(item, now, 0))

    def test_batch_fetch_preserves_existing_content(self) -> None:
        item = {
            "url": "https://example.com/article",
            "summary": "Existing RSS summary",
            "reading_metadata": {
                "description": "Existing description",
                "article_markdown": "Existing article",
            },
        }
        fetched = {
            "fetched_at": "2026-06-25T00:00:00+00:00",
            "source_url": item["url"],
            "final_url": item["url"],
            "content_type": "text/html",
            "status": "ok",
            "description": "Replacement description",
            "article_markdown": "Replacement article",
            "image_url": "https://example.com/cover.jpg",
        }
        with patch.object(page_metadata, "fetch_page_metadata", return_value=fetched):
            updated, changed, error = page_metadata.enrich_item_metadata(
                item,
                preserve_existing=True,
            )
        self.assertTrue(changed)
        self.assertEqual(error, "")
        self.assertEqual(updated["summary"], "Existing RSS summary")
        self.assertEqual(updated["reading_metadata"]["description"], "Existing description")
        self.assertEqual(updated["reading_metadata"]["article_markdown"], "Existing article")
        self.assertEqual(updated["image_url"], "https://example.com/cover.jpg")

    def test_main_prioritizes_never_attempted_then_oldest(self) -> None:
        recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
        records = [
            {
                "id": "recent",
                "title": "Recent",
                "url": "https://example.com/recent",
                "status": "ready",
                "reading_metadata": {"fetched_at": recent},
            },
            {
                "id": "never",
                "title": "Never",
                "url": "https://example.com/never",
                "status": "ready",
                "reading_metadata": {},
            },
            {
                "id": "old",
                "title": "Old",
                "url": "https://example.com/old",
                "status": "ready",
                "reading_metadata": {"fetched_at": "2020-01-01T00:00:00+00:00"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            items_path = Path(tmp) / "items.jsonl"
            items_path.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
                encoding="utf-8",
            )

            def fake_enrich(item: dict, timeout: int = 8, preserve_existing: bool = False):
                return item, False, ""

            argv = [
                "enrich_reading_metadata.py",
                "--items",
                str(items_path),
                "--reader-only",
                "--only-missing-reader-data",
                "--retry-after-days",
                "7",
                "--limit",
                "2",
            ]
            with patch.object(sys, "argv", argv), patch.object(
                enrich_reading_metadata,
                "enrich_item_metadata",
                side_effect=fake_enrich,
            ):
                enrich_reading_metadata.main()

            updated = [
                json.loads(line)
                for line in items_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        statuses = {
            record["id"]: (record.get("reading_metadata") or {}).get("reader_enrichment")
            for record in updated
        }
        self.assertIsNone(statuses["recent"])
        self.assertEqual(statuses["never"]["attempt_count"], 1)
        self.assertEqual(statuses["old"]["attempt_count"], 1)


if __name__ == "__main__":
    unittest.main()
