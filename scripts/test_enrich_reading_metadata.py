#!/usr/bin/env python3
from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import enrich_reading_metadata
import page_metadata


class ReadingMetadataRulesTest(unittest.TestCase):
    def test_fetch_page_metadata_retries_403_with_browser_headers(self) -> None:
        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://example.com/article"

            def read(self, _max_bytes: int) -> bytes:
                return b"""
                <html lang="en">
                  <head><title>Example article</title></head>
                  <body><article><p>This paragraph is long enough to be extracted as article text.</p></article></body>
                </html>
                """

        blocked = urllib.error.HTTPError(
            "https://example.com/article",
            403,
            "Forbidden",
            {},
            io.BytesIO(b""),
        )
        with patch.object(
            page_metadata.urllib.request,
            "urlopen",
            side_effect=[blocked, FakeResponse()],
        ) as urlopen:
            metadata = page_metadata.fetch_page_metadata("https://example.com/article")
        blocked.close()

        self.assertEqual(metadata["title"], "Example article")
        self.assertEqual(urlopen.call_count, 2)
        retry_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(
            retry_request.get_header("User-agent"),
            page_metadata.BROWSER_FALLBACK_USER_AGENT,
        )

    def test_fetch_page_metadata_extracts_site_name_and_published_date(self) -> None:
        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://example.com/world/story-2026-06-25/"

            def read(self, _max_bytes: int) -> bytes:
                return b"""
                <html lang="en">
                  <head>
                    <meta property="og:site_name" content="Example News">
                    <meta property="article:published_time" content="2026-06-25T12:30:00Z">
                    <title>Example article</title>
                  </head>
                  <body><article><p>This article paragraph is long enough to be extracted as article text.</p></article></body>
                </html>
                """

        with patch.object(page_metadata.urllib.request, "urlopen", return_value=FakeResponse()):
            metadata = page_metadata.fetch_page_metadata("https://example.com/world/story-2026-06-25/")

        self.assertEqual(metadata["site_name"], "Example News")
        self.assertEqual(metadata["published_at"], "2026-06-25")
        self.assertEqual(metadata["published_at_source"], "article:published_time")

    def test_html_article_markdown_uses_blank_lines_between_paragraphs(self) -> None:
        html = """
        <article>
          <h1>Example article</h1>
          <p>This is the first paragraph with enough text to pass the article filter.</p>
          <p>This is the second paragraph with enough text to remain a separate block.</p>
        </article>
        """

        markdown, method = page_metadata.extract_article_markdown(
            html,
            final_url="https://example.com/article",
            title="Example article",
        )

        self.assertEqual(method, "all-paragraphs")
        self.assertIn(
            "This is the first paragraph with enough text to pass the article filter.\n\n"
            "This is the second paragraph with enough text to remain a separate block.",
            markdown,
        )

    def test_text_to_markdown_preserves_paragraph_separators(self) -> None:
        markdown = page_metadata.text_to_markdown(
            "First paragraph has enough content to be useful.\n\n"
            "Second paragraph should stay separate in Markdown.",
            title="Example",
        )

        self.assertEqual(
            markdown,
            "# Example\n\n"
            "First paragraph has enough content to be useful.\n\n"
            "Second paragraph should stay separate in Markdown.",
        )

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
