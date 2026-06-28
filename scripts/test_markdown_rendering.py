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

    def test_translation_reader_keeps_blank_lines(self) -> None:
        markdown = "# 中文標題\n\n第一段。\n\n第二段。"

        self.assertEqual(
            local_web.item_translated_markdown(
                {"reading_metadata": {"translated_article_markdown_zh": markdown}}
            ),
            markdown,
        )

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
