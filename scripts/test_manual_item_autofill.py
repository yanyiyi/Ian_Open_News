#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_web


class ManualItemAutofillTest(unittest.TestCase):
    def test_infers_open_tech_track_from_open_source_ai_title(self) -> None:
        keyword_config = {
            "version": 1,
            "tracks": {
                "open-tech-open-industry": {
                    "keep_keywords": ["open source", "open source AI", "AI governance", "compliance"],
                    "skip_keywords": [],
                    "mechanism_keywords": ["transparency", "model provenance"],
                },
                "digital-humanities-local-knowledge": {
                    "keep_keywords": ["數位典藏", "文化記憶"],
                    "skip_keywords": [],
                    "mechanism_keywords": [],
                },
            },
        }
        context = local_web.build_editorial_context([], keyword_config)
        record = {
            "title": "Italy's Domyn to launch open source frontier AI model within a year",
            "url": "https://www.reuters.com/world/china/story-2026-06-25/",
            "source_name": "Reuters",
            "author": "",
            "published_at": "2026-06-25",
            "summary": "The model pitch emphasizes transparency, compliance, and model provenance.",
            "tags": [],
            "origin": "manual-web",
        }

        track, reason, choices = local_web.infer_manual_item_track(
            record,
            keyword_config,
            context,
            "digital-humanities-local-knowledge",
        )

        self.assertEqual(track, "open-tech-open-industry")
        self.assertIn("open source", reason)
        self.assertGreater(
            next(choice["score"] for choice in choices if choice["track"] == "open-tech-open-industry"),
            next(choice["score"] for choice in choices if choice["track"] == "digital-humanities-local-knowledge"),
        )

    def test_tag_suggestions_ignore_generated_ocf_boilerplate(self) -> None:
        record = {
            "title": "Italy's Domyn to launch open source frontier AI model within a year",
            "url": "https://example.com/story-2026-06-25/",
            "source_name": "Example News",
            "summary": "",
            "tags": [],
            "track": "open-tech-open-industry",
            "triage": {"matched_keywords": [], "skip_keywords": [], "recommendation": "suggest-skip"},
            "editorial_triage": {
                "zh_summary": "後續若要整理，請用 skill 補完整中文摘要、台灣/OCF 關聯與查核結果。",
                "summary_reason": "符合主線或既有收錄線索，可人工判斷。",
            },
        }

        self.assertNotIn("OCF", local_web.suggested_item_tags(record, [], limit=8))

    def test_tag_aliases_canonicalize_to_formal_labels(self) -> None:
        self.assertEqual(local_web.canonical_tag_label("OS"), "開放原始碼")
        self.assertEqual(local_web.canonical_tag_label("open source"), "開放原始碼")
        self.assertEqual(local_web.canonical_tag_label("OD"), "開放資料")

    def test_suggested_tags_use_triage_and_mechanism_keywords(self) -> None:
        record = {
            "title": "Open source AI model with compliance commitments",
            "url": "https://example.com/story-2026-06-25/",
            "source_name": "Example News",
            "summary": "The model pitch emphasizes transparency, compliance, and model provenance.",
            "tags": [],
            "track": "open-tech-open-industry",
            "triage": {
                "matched_keywords": ["open source"],
                "mechanism_keywords": ["compliance"],
                "skip_keywords": [],
                "recommendation": "suggest-keep",
            },
        }

        suggestions = local_web.suggested_item_tags(record, [], limit=8)

        self.assertIn("開放原始碼", suggestions)
        self.assertIn("法規政策", suggestions)

    def test_manual_autofill_adds_summary_date_notes_and_tags(self) -> None:
        keyword_config = {
            "version": 1,
            "tracks": {
                "open-tech-open-industry": {
                    "keep_keywords": ["open source"],
                    "skip_keywords": [],
                    "mechanism_keywords": ["compliance"],
                }
            },
        }
        context = local_web.build_editorial_context([], keyword_config)
        record = {
            "title": "Open source AI model with compliance commitments",
            "url": "https://example.com/news/story-2026-06-25/",
            "source_name": "Example News",
            "author": "",
            "published_at": "",
            "summary": "",
            "tags": [],
            "track": "open-tech-open-industry",
            "origin": "manual-web",
            "review": local_web.default_review(""),
        }
        metadata = {
            "description": "The company says the model will be released openly and documented for compliance review.",
            "published_at": "",
        }

        updated = local_web.apply_manual_item_autofill(record, metadata, [], keyword_config, context)

        self.assertEqual(updated["published_at"], "2026-06-25")
        self.assertIn("released openly", updated["summary"])
        self.assertIn("初步值得追", updated["review"]["notes"])
        self.assertIn("開放原始碼", updated["tags"])

    def test_fulltext_signal_uses_metadata_access_issue(self) -> None:
        item = {
            "title": "Blocked article",
            "summary": "",
            "reading_metadata": {
                "preferred_fulltext_url": "https://example.com/fulltext",
                "access_issue": "cloudflare-challenge",
                "needs_fulltext": "true",
            },
        }

        self.assertTrue(local_web.item_has_fulltext_signal(item))

    def test_newsletter_link_title_prefers_specific_openbook_label(self) -> None:
        markdown = """
## [9. Paradoxes of Openness: Power, Reciprocity, and the Governance of Scholarly Infrastructures](https://www.openbookpublishers.com/books/10.11647/obp.0528/chapters/10.11647/obp.0528.09)

## [10. From Data to Display: Infrastructures of Openness in the Making](https://www.openbookpublishers.com/books/10.11647/obp.0528/chapters/10.11647/obp.0528.10)
"""

        links = local_web.extract_markdown_links(markdown)

        self.assertEqual(
            links[1]["title"],
            "10. From Data to Display: Infrastructures of Openness in the Making",
        )

    def test_newsletter_link_candidates_skip_openbook_series_page(self) -> None:
        item = {
            "url": "https://www.openbookpublishers.com/books/10.11647/obp.0528",
            "reading_metadata": {
                "article_markdown": """
[Digital Humanities Series](https://www.openbookpublishers.com/series/2054-2429)

## [10. From Data to Display: Infrastructures of Openness in the Making](https://www.openbookpublishers.com/books/10.11647/obp.0528/chapters/10.11647/obp.0528.10)
"""
            },
        }

        candidates, skipped = local_web.newsletter_link_candidates(item)

        self.assertEqual([candidate["title"] for candidate in candidates], ["10. From Data to Display: Infrastructures of Openness in the Making"])
        self.assertEqual(skipped[0]["reason"], "系列、分類或作者索引頁")


if __name__ == "__main__":
    unittest.main()
