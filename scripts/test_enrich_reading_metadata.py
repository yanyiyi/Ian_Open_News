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

    def test_fetch_page_metadata_marks_repeated_401_as_manual_fulltext(self) -> None:
        first = urllib.error.HTTPError(
            "https://example.com/article",
            401,
            "HTTP Forbidden",
            {"content-type": "text/html; charset=utf-8"},
            io.BytesIO(b""),
        )
        second = urllib.error.HTTPError(
            "https://example.com/article",
            401,
            "HTTP Forbidden",
            {"content-type": "text/html; charset=utf-8"},
            io.BytesIO(b""),
        )
        with patch.object(
            page_metadata.urllib.request,
            "urlopen",
            side_effect=[first, second],
        ) as urlopen:
            metadata = page_metadata.fetch_page_metadata("https://example.com/article")
        first.close()
        second.close()

        self.assertEqual(metadata["access_issue"], "http-access-denied")
        self.assertEqual(metadata["needs_fulltext"], "true")
        self.assertEqual(metadata["fulltext_status"], "needs-manual")
        self.assertEqual(urlopen.call_count, 2)
        retry_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(
            retry_request.get_header("User-agent"),
            page_metadata.BROWSER_FALLBACK_USER_AGENT,
        )

    def test_fetch_page_metadata_drops_js_adblock_prompt_article(self) -> None:
        body = b"""
        <html lang="en">
          <head><title>nytimes.com</title></head>
          <body>
            <h1>nytimes.com</h1>
            <p>Please enable JS and disable any ad blocker</p>
          </body>
        </html>
        """
        first = urllib.error.HTTPError(
            "https://www.nytimes.com/2026/04/07/technology/google-ai-overviews-accuracy.html",
            403,
            "Forbidden",
            {"content-type": "text/html; charset=utf-8"},
            io.BytesIO(body),
        )
        second = urllib.error.HTTPError(
            "https://www.nytimes.com/2026/04/07/technology/google-ai-overviews-accuracy.html",
            403,
            "Forbidden",
            {"content-type": "text/html; charset=utf-8"},
            io.BytesIO(body),
        )
        with patch.object(
            page_metadata.urllib.request,
            "urlopen",
            side_effect=[first, second],
        ):
            metadata = page_metadata.fetch_page_metadata(
                "https://www.nytimes.com/2026/04/07/technology/google-ai-overviews-accuracy.html"
            )
        first.close()
        second.close()

        self.assertEqual(metadata["access_issue"], "http-access-denied")
        self.assertEqual(metadata["needs_fulltext"], "true")
        self.assertEqual(metadata["excerpt"], "")
        self.assertNotIn("article_text", metadata)
        self.assertNotIn("article_markdown", metadata)
        self.assertIn("JavaScript", metadata["access_issue_note"])

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

    def test_published_date_from_url_handles_slug_suffix_date(self) -> None:
        self.assertEqual(
            page_metadata.published_date_from_url(
                "https://www.reuters.com/world/china/story-title-2026-06-25/"
            ),
            "2026-06-25",
        )

    def test_arxiv_abs_prefers_experimental_html_fulltext(self) -> None:
        long_body = " ".join(["This full text paragraph is long enough for extraction."] * 18)

        class AbsResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            def __enter__(self) -> "AbsResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://arxiv.org/abs/2606.09648"

            def read(self, _max_bytes: int) -> bytes:
                return b"""
                <html lang="en">
                  <head>
                    <meta property="og:url" content="https://arxiv.org/abs/2606.09648v1">
                    <title>ArtiFact</title>
                  </head>
                  <body><main><p>Short abstract only.</p></main></body>
                </html>
                """

        class HtmlResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            def __enter__(self) -> "HtmlResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://arxiv.org/html/2606.09648v1"

            def read(self, _max_bytes: int) -> bytes:
                return f"""
                <html lang="en">
                  <head><title>ArtiFact</title></head>
                  <body><article><p>{long_body}</p></article></body>
                </html>
                """.encode()

        with patch.object(page_metadata.urllib.request, "urlopen", side_effect=[AbsResponse(), HtmlResponse()]):
            metadata = page_metadata.fetch_page_metadata("https://arxiv.org/abs/2606.09648")

        self.assertEqual(metadata["final_url"], "https://arxiv.org/html/2606.09648v1")
        self.assertEqual(metadata["landing_url"], "https://arxiv.org/abs/2606.09648")
        self.assertEqual(metadata["fulltext_source"], "preferred-html")
        self.assertGreater(metadata["article_markdown_chars"], 500)

    def test_openbook_landing_records_blocked_html_fulltext_url(self) -> None:
        class LandingResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            def __enter__(self) -> "LandingResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://www.openbookpublishers.com/books/10.11647/obp.0528/chapters/10.11647/obp.0528.02"

            def read(self, _max_bytes: int) -> bytes:
                return b"""
                <html lang="en">
                  <head>
                    <title>Open Book chapter</title>
                    <meta name="citation_fulltext_html_url" content="http://books.openbookpublishers.com/10.11647/obp.0528/ch2.xhtml">
                    <meta name="description" content="Chapter landing page">
                  </head>
                  <body><main><p>Landing page summary.</p></main></body>
                </html>
                """

        class ChallengeResponse:
            headers = {
                "content-type": "text/html; charset=UTF-8",
                "x-amzn-waf-action": "challenge",
            }
            status = 202

            def __enter__(self) -> "ChallengeResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def geturl(self) -> str:
                return "https://books.openbookpublishers.com/10.11647/obp.0528/ch2.xhtml"

            def read(self, _max_bytes: int) -> bytes:
                return b""

        with patch.object(page_metadata.urllib.request, "urlopen", side_effect=[LandingResponse(), ChallengeResponse()]):
            metadata = page_metadata.fetch_page_metadata(
                "https://www.openbookpublishers.com/books/10.11647/obp.0528/chapters/10.11647/obp.0528.02"
            )

        self.assertEqual(metadata["preferred_fulltext_url"], "https://books.openbookpublishers.com/10.11647/obp.0528/ch2.xhtml")
        self.assertEqual(metadata["fulltext_status"], "blocked")
        self.assertEqual(metadata["access_issue"], "aws-waf-challenge")
        self.assertEqual(metadata["needs_fulltext"], "true")

    def test_openbook_direct_xhtml_405_records_manual_fulltext_signal(self) -> None:
        error = urllib.error.HTTPError(
            "https://books.openbookpublishers.com/10.11647/obp.0528/ch2.xhtml",
            405,
            "Not Allowed",
            {"content-type": "text/html; charset=UTF-8"},
            io.BytesIO(b""),
        )
        with patch.object(page_metadata.urllib.request, "urlopen", side_effect=error):
            metadata = page_metadata.fetch_page_metadata(
                "https://books.openbookpublishers.com/10.11647/obp.0528/ch2.xhtml"
            )
        error.close()

        self.assertEqual(metadata["access_issue"], "openbook-fulltext-blocked")
        self.assertEqual(metadata["needs_fulltext"], "true")
        self.assertEqual(metadata["fulltext_status"], "needs-manual")

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

    def test_wysiwyg_article_blocks_beat_related_cards(self) -> None:
        html = """
        <html>
          <head><title>Sunset and Renew</title></head>
          <body>
            <div class="body1">
              <div class="-mx:a -xw:5 wysiwyg">
                <p>Republicans and Democrats agree the current social media ecosystem serves neither consumers nor citizens.</p>
                <p>Merely repealing Section 230 is insufficient because lawmakers must also protect human speech.</p>
              </div>
              <div class="-mx:a -xw:5 wysiwyg">
                <p>Our proposed repeal and renew approach would remove the liability shield for algorithmic amplification.</p>
                <p>The distinction between protected speech and harmful algorithmic amplification becomes clear in public interest systems.</p>
              </div>
            </div>
            <article class="card1">
              <h3>Artificial Intelligence and Democracy: Campaigns, Elections, Movements, and Deliberation</h3>
              <p>A related card about generative AI is long enough to look article-like but should not be selected.</p>
            </article>
          </body>
        </html>
        """

        markdown, method = page_metadata.extract_article_markdown(
            html,
            final_url="https://ash.harvard.edu/articles/sunset-and-renew-section-230-should-protect-human-speech-not-algorithmic-virality/",
            title="Sunset and Renew",
        )

        self.assertEqual(method, "semantic-block")
        self.assertIn("Republicans and Democrats agree", markdown)
        self.assertIn("repeal and renew approach", markdown)
        self.assertNotIn("Artificial Intelligence and Democracy", markdown)

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
