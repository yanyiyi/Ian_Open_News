#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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

    def test_newsletter_link_candidates_keep_source_recommendation_cards(self) -> None:
        recommended_url = "https://www.itpro.com/business/data-and-insights/amazon-opensearch-update"
        item = {
            "url": "https://www.itpro.com/software/open-source/example",
            "reading_metadata": {
                "article_markdown": (
                    "## ITPro 建議文章\n\n"
                    f"- [Amazon OpenSearch update targets performance boosts and lower costs]({recommended_url})"
                ),
                "related_article_links": [
                    {
                        "title": "Amazon OpenSearch update targets performance boosts and lower costs",
                        "url": recommended_url,
                    }
                ],
            },
        }

        candidates, skipped = local_web.newsletter_link_candidates(item)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "Amazon OpenSearch update targets performance boosts and lower costs")
        self.assertEqual(candidates[0]["reason"], "來源網站的建議文章卡片")
        self.assertEqual(skipped, [])

    def test_newsletter_link_candidates_show_translated_title_with_original(self) -> None:
        url = "https://example.org/news/open-source-policy"
        item = {
            "url": "https://newsletter.example.org/archive",
            "reading_metadata": {
                "article_markdown": f"""
## [How open source policy moves](https://example.org/news/open-source-policy)

[Read more]({url})
""",
                "translated_article_markdown_zh": f"""
## [開源政策如何成形](https://example.org/news/open-source-policy)

[閱讀更多]({url})
""",
            },
        }

        candidates, _skipped = local_web.newsletter_link_candidates(item)

        self.assertEqual(candidates[0]["title"], "How open source policy moves")
        self.assertEqual(candidates[0]["display_title"], "開源政策如何成形")
        self.assertEqual(candidates[0]["original_title"], "How open source policy moves")
        self.assertIn("nl-cand-original", local_web.newsletter_link_title_html(candidates[0]))

    def test_newsletter_link_candidates_keep_translated_title_after_tracking_resolution(self) -> None:
        tracking_url = "https://click.mlsend.com/link/c/YT0xMjM"
        real_url = "https://example.org/news/open-source-policy"
        item = {
            "url": "https://newsletter.example.org/archive",
            "reading_metadata": {
                "article_markdown": f"""
## [How open source policy moves]({tracking_url})

[Read more]({tracking_url})
""",
                "translated_article_markdown_zh": f"""
## [開源政策如何成形]({tracking_url})

[閱讀更多]({tracking_url})
""",
            },
        }
        original_resolver = local_web.resolve_tracking_links
        local_web.resolve_tracking_links = lambda urls: {tracking_url: real_url}
        try:
            candidates, _skipped = local_web.newsletter_link_candidates(item)
        finally:
            local_web.resolve_tracking_links = original_resolver

        self.assertEqual(candidates[0]["url"], real_url)
        self.assertEqual(candidates[0]["tracking_url"], tracking_url)
        self.assertEqual(candidates[0]["title"], "How open source policy moves")
        self.assertEqual(candidates[0]["display_title"], "開源政策如何成形")
        self.assertEqual(candidates[0]["original_title"], "How open source policy moves")

    def test_source_add_href_prefills_rsshub_bridge_fields(self) -> None:
        href = local_web.source_add_href(
            "http://127.0.0.1:1200/ptt/bbs/Tech_Job",
            "open-tech-open-industry",
            "PTT Tech Job",
            "https://www.ptt.cc/bbs/Tech_Job/index.html",
            served_via="rsshub@local",
            bridge="ptt/bbs/Tech_Job",
        )
        query = parse_qs(urlparse(href).query)

        self.assertEqual(query["feed_url"], ["http://127.0.0.1:1200/ptt/bbs/Tech_Job"])
        self.assertEqual(query["site_url"], ["https://www.ptt.cc/bbs/Tech_Job/index.html"])
        self.assertEqual(query["served_via"], ["rsshub@local"])
        self.assertEqual(query["bridge"], ["ptt/bbs/Tech_Job"])

    def test_workflow_search_haystack_includes_fulltext_fields(self) -> None:
        item = {
            "id": "item-fulltext",
            "title": "普通標題",
            "reading_metadata": {
                "codex_translated_article_markdown_zh": "# 中文全文\n\n這裡提到罕見詞彙：浮動資料信託。",
                "edited_markdown": "# 編輯版\n\n另一個罕見詞彙：自治資料庫。",
            },
        }

        self.assertTrue(local_web.item_matches_text_filter(item, "浮動資料信託"))
        self.assertTrue(local_web.item_matches_text_filter(item, "自治資料庫"))


if __name__ == "__main__":
    unittest.main()
