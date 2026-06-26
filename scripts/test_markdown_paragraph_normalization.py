#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import normalize_markdown_paragraphs as normalize  # noqa: E402


class MarkdownParagraphNormalizationTest(unittest.TestCase):
    def test_inserts_blank_lines_between_flat_prose_blocks(self) -> None:
        markdown = "# Title\nFirst paragraph.\nSecond paragraph."

        self.assertEqual(
            normalize.normalize_flat_markdown(markdown),
            "# Title\n\nFirst paragraph.\n\nSecond paragraph.",
        )

    def test_keeps_consecutive_list_items_together(self) -> None:
        markdown = "# Title\n- First item\n- Second item\nClosing paragraph."

        self.assertEqual(
            normalize.normalize_flat_markdown(markdown),
            "# Title\n\n- First item\n- Second item\n\nClosing paragraph.",
        )

    def test_keeps_table_rows_together(self) -> None:
        markdown = "| A | B |\n| --- | --- |\n| 1 | 2 |\nNext paragraph."

        self.assertEqual(
            normalize.normalize_flat_markdown(markdown),
            "| A | B |\n| --- | --- |\n| 1 | 2 |\n\nNext paragraph.",
        )

    def test_keeps_code_fence_lines_together(self) -> None:
        markdown = "# Title\n```python\nprint('hello')\n```\nAfterward."

        self.assertEqual(
            normalize.normalize_flat_markdown(markdown),
            "# Title\n\n```python\nprint('hello')\n```\n\nAfterward.",
        )

    def test_normalizes_generated_article_markdown_and_char_count(self) -> None:
        record = {
            "reading_metadata": {
                "article_markdown": "# Title\nFirst paragraph.\nSecond paragraph.\nThird paragraph.\nFourth paragraph.\nFifth paragraph.",
                "article_markdown_chars": 88,
                "article_markdown_method": "semantic-block",
            }
        }

        changed = normalize.normalize_item(record, min_single_breaks=3)

        metadata = record["reading_metadata"]
        self.assertEqual(changed["article_markdown"], 1)
        self.assertIn("First paragraph.\n\nSecond paragraph.", metadata["article_markdown"])
        self.assertEqual(metadata["article_markdown_chars"], len(metadata["article_markdown"]))

    def test_skips_pdf_article_markdown_by_default(self) -> None:
        record = {
            "reading_metadata": {
                "article_markdown": "# Title\nFirst paragraph.\nSecond paragraph.\nThird paragraph.\nFourth paragraph.\nFifth paragraph.",
                "article_markdown_method": "pdf-markitdown",
            }
        }

        changed = normalize.normalize_item(record, min_single_breaks=3)

        self.assertFalse(changed)

    def test_normalizes_provider_translation_markdown(self) -> None:
        record = {
            "reading_metadata": {
                "translated_article_markdown_zh": "# 標題\n第一段。\n第二段。\n第三段。\n第四段。",
                "translated_article_markdown_zh_chars": 10,
            }
        }

        changed = normalize.normalize_item(record, min_single_breaks=3)

        metadata = record["reading_metadata"]
        self.assertEqual(changed["translated_article_markdown_zh"], 1)
        self.assertIn("第一段。\n\n第二段。", metadata["translated_article_markdown_zh"])
        self.assertEqual(
            metadata["translated_article_markdown_zh_chars"],
            len(metadata["translated_article_markdown_zh"]),
        )


if __name__ == "__main__":
    unittest.main()
