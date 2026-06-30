#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_translate_article as translate  # noqa: E402


class TranslationMarkdownTest(unittest.TestCase):
    def test_source_markdown_keeps_blank_lines(self) -> None:
        markdown = "# Title\n\nFirst paragraph.\n\nSecond paragraph."
        record = {"reading_metadata": {"article_markdown": markdown}}

        self.assertEqual(translate.source_markdown(record), markdown)

    def test_source_markdown_prefers_edited_fulltext(self) -> None:
        original = "# Original\n\nOld paragraph."
        edited = "# Original\n\nCorrected paragraph.\n\nAdded context."
        record = {
            "reading_metadata": {
                "article_markdown": original,
                "edited_markdown": edited,
            }
        }

        self.assertEqual(translate.source_markdown(record), edited)

    def test_source_markdown_uses_original_when_edited_fulltext_is_chinese(self) -> None:
        original = "# Original\n\nLong English paragraph."
        edited = "# 中文標題\n\n已人工修正的中文翻譯。"
        record = {
            "reading_metadata": {
                "article_markdown": original,
                "edited_markdown": edited,
                "edited_markdown_base": "zh",
            }
        }

        self.assertEqual(translate.source_markdown(record), original)

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

    def test_apply_translation_replaces_legacy_provider_primary_markdown(self) -> None:
        record = {
            "reading_metadata": {
                "translated_article_markdown_zh": "# 舊短文\n\n只有一小段。",
                "translation_source": "Ollama gemma4:12b MLX",
            }
        }
        markdown = "# 新長文\n\n第一段。\n\n第二段。"

        translate.apply_translation(
            record,
            {
                "zh_title": "新長文",
                "zh_markdown": markdown,
                "note": "test",
            },
            "en",
            "ollama-gemma4",
            source_hash="new-source-hash",
        )

        metadata = record["reading_metadata"]
        self.assertEqual(metadata["translated_article_markdown_zh"], markdown)
        self.assertEqual(metadata["ollama_gemma4_translated_article_markdown_zh"], markdown)
        self.assertEqual(metadata["translation_source_hash"], "new-source-hash")
        self.assertEqual(metadata["ollama_gemma4_translation_source_hash"], "new-source-hash")

    def test_write_record_does_not_clobber_other_current_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "items.jsonl"
            translate.write_jsonl(
                path,
                [
                    {"id": "item-a", "value": "current-a"},
                    {"id": "item-b", "value": "current-b"},
                ],
            )

            translate.write_record(path, {"id": "item-a", "value": "translated-a"})

            rows = translate.load_jsonl(path)
            self.assertEqual(rows[0], {"id": "item-a", "value": "translated-a"})
            self.assertEqual(rows[1], {"id": "item-b", "value": "current-b"})


if __name__ == "__main__":
    unittest.main()
