#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_translate_article as translate  # noqa: E402


class TranslationMarkdownTest(unittest.TestCase):
    def test_source_markdown_keeps_blank_lines(self) -> None:
        markdown = "# Title\n\nFirst paragraph.\n\nSecond paragraph."
        record = {"reading_metadata": {"article_markdown": markdown}}

        self.assertEqual(translate.source_markdown(record), markdown)

    def test_apply_translation_keeps_blank_lines(self) -> None:
        record = {"reading_metadata": {}}
        markdown = "# 中文標題\n\n第一段。\n\n第二段。"

        translate.apply_translation(
            record,
            {
                "zh_title": "中文標題",
                "zh_markdown": markdown,
                "note": "test",
            },
            "en",
            "codex",
        )

        self.assertEqual(
            record["reading_metadata"]["translated_article_markdown_zh"],
            markdown,
        )


if __name__ == "__main__":
    unittest.main()
