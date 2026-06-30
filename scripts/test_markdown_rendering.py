#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_web  # noqa: E402


class MarkdownRenderingTest(unittest.TestCase):
    def test_article_markdown_reader_keeps_blank_lines(self) -> None:
        markdown = "# Title\n\nFirst paragraph.\n\nSecond paragraph."

        self.assertEqual(
            local_web.item_article_markdown(
                {"reading_metadata": {"article_markdown": markdown}}
            ),
            markdown,
        )

    def test_access_prompt_is_not_treated_as_article_body(self) -> None:
        item = {
            "id": "item-test",
            "url": "https://www.nytimes.com/2026/04/07/technology/google-ai-overviews-accuracy.html",
            "reading_metadata": {
                "access_issue": "http-access-denied",
                "needs_fulltext": "true",
                "excerpt": "Please enable JS and disable any ad blocker",
                "article_text": "Please enable JS and disable any ad blocker",
                "article_markdown": "# nytimes.com\n\nPlease enable JS and disable any ad blocker",
            },
            "summary": "Please enable JS and disable any ad blocker",
        }

        self.assertEqual(local_web.item_article_text(item), "")
        self.assertEqual(local_web.item_article_markdown(item), "")
        self.assertEqual(local_web.item_original_summary(item), "")
        self.assertEqual(local_web.markdown_source_text(item), "")
        self.assertTrue(local_web.item_has_fulltext_signal(item))
        self.assertEqual(local_web.translation_actions_html(item, "item-test", "/items/view?id=item-test"), "")

    def test_translation_reader_keeps_blank_lines(self) -> None:
        markdown = "# 中文標題\n\n第一段。\n\n第二段。"

        self.assertEqual(
            local_web.item_translated_markdown(
                {"reading_metadata": {"translated_article_markdown_zh": markdown}}
            ),
            markdown,
        )

    def test_legacy_translation_source_infers_twinkle_provider(self) -> None:
        markdown = "# 中文標題\n\n第一段。"
        item = {
            "reading_metadata": {
                "translated_article_markdown_zh": markdown,
                "translation_source": "TwinkleAI:Gemma-3-4B-T1-IT",
                "translation_generated_at": "2026-06-29T04:32:28+00:00",
            }
        }

        self.assertEqual(local_web.item_translation_entries(item), [("ollama-twinkle", markdown)])
        self.assertEqual(local_web.item_provider_translation_markdown(item, "codex"), "")
        self.assertEqual(local_web.item_provider_translation_markdown(item, "ollama-twinkle"), markdown)

        rendered = local_web.translation_panels_html(item)
        self.assertIn('<div class="section-kicker">翻譯全文</div>', rendered)
        self.assertIn("翻譯來源：TwinkleAI:Gemma-3-4B-T1-IT", rendered)
        self.assertNotIn("Codex 自動翻譯", rendered)

    def test_legacy_codex_translation_still_available_without_source(self) -> None:
        markdown = "# 中文標題\n\n第一段。"
        item = {"reading_metadata": {"translated_article_markdown_zh": markdown}}

        self.assertEqual(local_web.item_translation_entries(item), [("codex", markdown)])
        self.assertEqual(local_web.item_provider_translation_markdown(item, "codex"), markdown)

    def test_chinese_edited_fulltext_kicker_marks_translation(self) -> None:
        item = {"reading_metadata": {"edited_markdown": "中文全文", "edited_markdown_base": "zh"}}

        self.assertEqual(local_web.edited_fulltext_kicker(item), "翻譯全文（已手動修正）")

    def test_inferred_chinese_language_does_not_hide_english_fulltext_translation_actions(self) -> None:
        item = {
            "id": "item-english",
            "title": "中文標題",
            "reading_metadata": {
                "original_language": "zh",
                "original_language_source": "推斷",
                "article_markdown": (
                    "# G7 Vision on AI openness opportunities and shared language\n\n"
                    "This document is addressed to the broader AI ecosystem of G7 members and beyond. "
                    "It may serve as a reference for institutions, companies, open source communities, "
                    "civil society, researchers, public authorities, and model providers. "
                    "The objective is to call for greater clarity in the use of terminology describing AI openness."
                ),
            },
        }

        self.assertEqual(local_web.item_original_language(item), "en")
        self.assertTrue(local_web.translation_actions_html(item, "item-english", "/items/view?id=item-english"))

    def test_edited_markdown_reader_does_not_collapse_blank_lines(self) -> None:
        markdown = "第一行\n\n第二段"

        self.assertEqual(
            local_web.item_edited_markdown(
                {"reading_metadata": {"edited_markdown": markdown}}
            ),
            markdown,
        )

    def test_default_rendering_treats_single_newline_as_soft_break(self) -> None:
        rendered = local_web.markdown_to_html("第一行\n第二行")

        self.assertEqual(rendered, "<p>第一行 第二行</p>")

    def test_edited_fulltext_can_preserve_single_newlines(self) -> None:
        rendered = local_web.markdown_to_html(
            "第一行\n第二行\n\n下一段",
            preserve_soft_breaks=True,
        )

        self.assertEqual(rendered, "<p>第一行<br>\n第二行</p>\n<p>下一段</p>")

    def test_heading_normalizes_english_possessive_apostrophe(self) -> None:
        rendered = local_web.markdown_to_html(
            "### Delivering the UK Government\u2019s Test, Learn and Grow programme"
        )
        rendered_spaced = local_web.markdown_to_html("### Delivering the UK Government\u2019 s Test")

        self.assertIn(
            "<h3>Delivering the UK Government&#x27;s Test, Learn and Grow programme</h3>",
            rendered,
        )
        self.assertIn("Government&#x27;s Test", rendered_spaced)

    def test_fenced_code_block_renders_without_raw_fences(self) -> None:
        rendered = local_web.markdown_to_html(
            "# 標題\n\n```\nZDNET 的重點摘要：設計人類與 AI 之間的健康關係。\n```\n\n下一段",
            preserve_soft_breaks=True,
        )

        self.assertIn(
            "<pre><code>ZDNET 的重點摘要：設計人類與 AI 之間的健康關係。</code></pre>",
            rendered,
        )
        self.assertNotIn("```", rendered)

    def test_fulltext_edit_storage_keeps_newlines_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items_path = Path(tmp) / "items.jsonl"
            candidates_path = Path(tmp) / "candidates.jsonl"
            local_web.write_jsonl(items_path, [{"id": "item-test", "reading_metadata": {}}])
            local_web.write_jsonl(candidates_path, [])
            original_items = local_web.ITEMS
            original_candidates = local_web.CANDIDATES
            local_web.ITEMS = items_path
            local_web.CANDIDATES = candidates_path
            try:
                handler = local_web.Handler.__new__(local_web.Handler)
                markdown = "第一行\n第二行\n\n下一段"
                saved = handler._apply_edited_markdown(
                    "item-test",
                    markdown,
                    "",
                    "original",
                    "test",
                )
                stored = local_web.load_jsonl(items_path)[0]["reading_metadata"]["edited_markdown"]
            finally:
                local_web.ITEMS = original_items
                local_web.CANDIDATES = original_candidates

        self.assertTrue(saved)
        self.assertEqual(stored, markdown)


if __name__ == "__main__":
    unittest.main()
