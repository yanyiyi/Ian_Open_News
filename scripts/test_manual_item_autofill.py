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


if __name__ == "__main__":
    unittest.main()
