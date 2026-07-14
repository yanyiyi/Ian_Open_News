#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_translate_article  # noqa: E402
import local_web  # noqa: E402
import render_ghpages_reader  # noqa: E402


class MarkdownRenderingTest(unittest.TestCase):
    def test_uploaded_pdf_fulltext_is_readable_without_remote_refresh(self) -> None:
        item = {
            "origin": "manual-pdf",
            "source_type": "pdf-upload",
            "reading_metadata": {
                "article_markdown": "# Uploaded paper\n\nComplete PDF body.",
                "fulltext_source": "uploaded-pdf",
            },
        }

        self.assertTrue(local_web.item_has_readable_fulltext(item))

    def test_integrated_pdf_article_is_preferred_for_reading(self) -> None:
        item = {"id": "item-integrated", "reading_metadata": {"article_markdown": "# Broken extraction"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            article_dir = Path(tmpdir)
            (article_dir / "item-integrated.md").write_text(
                "# Complete article\n\n```tsv\nA\tB\n1\t2\n```",
                encoding="utf-8",
            )
            with patch.object(local_web, "PDF_ARTICLES_DIR", article_dir):
                markdown = local_web.item_article_markdown(item)

        self.assertIn("# Complete article", markdown)
        self.assertNotIn("Broken extraction", markdown)

    def test_read_more_preserves_uploaded_pdf_body(self) -> None:
        item = {
            "id": "item-uploaded-pdf-test",
            "url": "https://doi.org/10.0000/example",
            "origin": "manual-pdf",
            "source_type": "pdf-upload",
            "reading_metadata": {
                "article_markdown": "# Uploaded paper\n\nComplete PDF body.",
                "fulltext_source": "uploaded-pdf",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            path.write_text(json.dumps(item) + "\n", encoding="utf-8")
            with patch.object(local_web, "enrich_item_metadata", return_value=(item, False, "")) as enrich:
                found, changed, _updated, error = local_web.Handler.update_read_more_record(None, path, item["id"])

        self.assertTrue(found)
        self.assertFalse(changed)
        self.assertEqual(error, "")
        enrich.assert_called_once_with(item, preserve_existing=True)

    def test_pdf_normalization_recovers_from_redirect_overwrite(self) -> None:
        pdf_text = "Original PDF paragraph.\n\n" + ("Substantive research text. " * 30)
        item = {
            "id": "item-pdf-redirect-test",
            "title": "Uploaded paper",
            "origin": "manual-pdf",
            "reading_metadata": {
                "article_markdown": "# Redirecting",
                "article_text": pdf_text,
                "fulltext_source": "uploaded-pdf",
            },
        }

        updated, changed, error = local_web.normalize_pdf_markdown_item(item)

        self.assertTrue(changed)
        self.assertEqual(error, "")
        self.assertIn("Original PDF paragraph.", local_web.item_article_markdown(updated))
        self.assertNotIn("Redirecting", local_web.item_article_markdown(updated))

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

    def test_long_edited_translation_hash_matches_actual_translate_source(self) -> None:
        edited = "# Long OSPO Report\n\n" + ("Open source programme office context.\n\n" * 2500)
        item = {
            "id": "item-long",
            "title": "Long OSPO Report",
            "reading_metadata": {
                "article_markdown": "# Wrong short source\n\nAttribution 4.0 International",
                "edited_markdown": edited,
                "edited_markdown_base": "original",
                "original_language": "en",
            },
        }
        source_hash = codex_translate_article.hashlib.sha1(
            codex_translate_article.source_markdown(item).encode("utf-8")
        ).hexdigest()[:16]
        item["reading_metadata"].update(
            {
                "codex_translated_article_markdown_zh": "# 中文報告\n\n已翻譯。",
                "codex_translation_source_hash": source_hash,
            }
        )

        self.assertEqual(local_web.item_translation_source_hash(item), source_hash)
        self.assertFalse(local_web.item_provider_translation_is_stale(item, "codex"))

    def test_translation_source_hash_includes_layout_preserving_pdf_tables(self) -> None:
        item = {
            "id": "item-table-hash",
            "reading_metadata": {"article_markdown": "# Source\n\nBody."},
        }
        tables = "## Table 1\n\n```text\nColumn A        Column B\n```"
        with patch.object(local_web, "item_pdf_tables_markdown", return_value=tables):
            source = local_web.item_translation_source_markdown(item)
            source_hash = local_web.item_translation_source_hash(item)

        self.assertIn("Column A        Column B", source)
        self.assertEqual(
            local_web.hashlib.sha1(source.encode("utf-8")).hexdigest()[:16],
            source_hash,
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
            '<h3 id="delivering-the-uk-governments-test-learn-and-grow-programme">'
            "Delivering the UK Government&#x27;s Test, Learn and Grow programme</h3>",
            rendered,
        )
        self.assertIn("Government&#x27;s Test", rendered_spaced)

    def test_article_body_prefers_traditional_chinese_serif_at_regular_weight(self) -> None:
        rendered = local_web.page("Typography test", "").decode("utf-8")

        self.assertIn('--article-serif: "Noto Serif TC",', rendered)
        self.assertIn(
            "font-family: var(--article-serif);\n      font-weight: 400;",
            rendered,
        )

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

    def test_fenced_code_block_preserves_fixed_width_table_columns(self) -> None:
        rendered = local_web.markdown_to_html(
            "## Table 1\n\n```text\nColumn A        Column B\nvalue           result\n```"
        )

        self.assertIn("Column A        Column B", rendered)
        self.assertIn("value           result", rendered)

    def test_tsv_fence_renders_as_html_table(self) -> None:
        rendered = local_web.markdown_to_html(
            "## Table 1\n\n```tsv\nColumn A\tColumn B\nvalue\tresult\n```"
        )

        self.assertIn('<table class="pdf-layout-table">', rendered)
        self.assertIn("<th>Column A</th><th>Column B</th>", rendered)
        self.assertIn("<td>value</td><td>result</td>", rendered)
        self.assertNotIn("```tsv", rendered)

    def test_pipe_table_renders_as_html_table_with_inline_markdown(self) -> None:
        rendered = local_web.markdown_to_html(
            "| 欄位 | 內容 |\n"
            "|:---|---:|\n"
            "| **作者** | [Nicholas](https://example.test/author) |\n"
            "| 關鍵詞 | 開源<br>數位主權 |",
            preserve_soft_breaks=True,
        )

        self.assertIn('<table class="pdf-layout-table markdown-table">', rendered)
        self.assertIn('<th style="text-align:left">欄位</th>', rendered)
        self.assertIn('<th style="text-align:right">內容</th>', rendered)
        self.assertIn("<strong>作者</strong>", rendered)
        self.assertIn('href="https://example.test/author"', rendered)
        self.assertIn("開源<br>數位主權", rendered)
        self.assertNotIn("<p>| 欄位 |", rendered)

    def test_pipe_table_keeps_escaped_and_code_span_pipes_in_cells(self) -> None:
        rendered = local_web.markdown_to_html(
            "| 語法 | 說明 |\n"
            "|---|---|\n"
            r"| A \| B | `x|y` |"
        )

        self.assertIn("A | B", rendered)
        self.assertIn("<code>x|y</code>", rendered)

    def test_toc_fragment_links_match_unicode_heading_fallback_ids(self) -> None:
        rendered = local_web.markdown_to_html(
            "## 目錄\n\n"
            "- [1. 引言](#1-引言)\n"
            "- [附錄 A：開源定義與 OSAI／OSS 比較](#附錄-a開源定義與-osaioss-比較)\n\n"
            "## 1. 引言\n\n"
            "## 附錄 A：開源定義與 OSAI／OSS 比較"
        )

        self.assertIn('<a href="#1-引言">1. 引言</a>', rendered)
        self.assertIn('<h2 id="1-引言">1. 引言</h2>', rendered)
        self.assertIn('<a href="#附錄-a開源定義與-osaioss-比較">', rendered)
        self.assertIn('<h2 id="附錄-a開源定義與-osaioss-比較">', rendered)

    def test_explicit_english_heading_id_is_stable_and_hidden_from_title(self) -> None:
        rendered = local_web.markdown_to_html(
            "- [中文章節](#public-sector-ai)\n\n"
            "## 中文章節 {#public-sector-ai}"
        )

        self.assertIn('<a href="#public-sector-ai">中文章節</a>', rendered)
        self.assertIn('<h2 id="public-sector-ai">中文章節</h2>', rendered)
        self.assertNotIn("{#public-sector-ai}", rendered)

    def test_duplicate_fallback_heading_ids_are_unique(self) -> None:
        rendered = local_web.markdown_to_html("## 結論\n\n## 結論")

        self.assertIn('<h2 id="結論">結論</h2>', rendered)
        self.assertIn('<h2 id="結論-1">結論</h2>', rendered)

    def test_public_reader_includes_local_table_layout_styles(self) -> None:
        rendered = render_ghpages_reader.page_shell("測試", "<p>內容</p>", current="article", depth=1)

        self.assertIn(".article-main { display: grid; grid-template-columns: minmax(0, 1fr);", rendered)
        self.assertIn(".pdf-table-scroll {", rendered)
        self.assertIn("width: 100%;", rendered)
        self.assertIn("max-width: 100%;", rendered)
        self.assertIn("min-width: 0;", rendered)
        self.assertIn("overflow-x: auto;", rendered)
        self.assertIn("width: max-content;", rendered)
        self.assertIn("min-width: 130px;", rendered)
        self.assertIn("max-width: 300px;", rendered)

    def test_fulltext_edit_storage_keeps_newlines_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items_path = Path(tmp) / "items.jsonl"
            candidates_path = Path(tmp) / "candidates.jsonl"
            local_web.write_jsonl(items_path, [{"id": "item-test", "reading_metadata": {}}])
            local_web.write_jsonl(candidates_path, [])
            original_items = local_web.ITEMS
            original_candidates = local_web.CANDIDATES
            original_fulltext_dir = local_web.fulltext_store.FULLTEXT_DIR
            local_web.ITEMS = items_path
            local_web.CANDIDATES = candidates_path
            local_web.fulltext_store.FULLTEXT_DIR = Path(tmp) / "fulltext"
            local_web.fulltext_store._STORE_CACHE.clear()
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
                # 寫入後重欄位在側檔，讀回要經 hydrate 才是完整形狀
                record = local_web.load_jsonl(items_path)[0]
                local_web.fulltext_store.hydrate_item(record)
                stored = record["reading_metadata"]["edited_markdown"]
            finally:
                local_web.ITEMS = original_items
                local_web.CANDIDATES = original_candidates
                local_web.fulltext_store.FULLTEXT_DIR = original_fulltext_dir
                local_web.fulltext_store._STORE_CACHE.clear()

        self.assertTrue(saved)
        self.assertEqual(stored, markdown)

    def test_clear_edited_markdown_keeps_original_and_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items_path = Path(tmp) / "items.jsonl"
            candidates_path = Path(tmp) / "candidates.jsonl"
            original = "# Original\n\nEnglish source."
            translated = "# 中文\n\n自動翻譯。"
            edited = "# 錯貼內容\n\n不應繼續覆蓋。"
            local_web.write_jsonl(
                items_path,
                [
                    {
                        "id": "item-test",
                        "review": {},
                        "reading_metadata": {
                            "article_markdown": original,
                            "translated_article_markdown_zh": translated,
                            "edited_markdown": edited,
                            "edited_markdown_chars": len(edited),
                            "edited_markdown_base": "zh",
                            "edited_markdown_at": "2026-07-01T00:00:00+00:00",
                        },
                    }
                ],
            )
            local_web.write_jsonl(candidates_path, [])
            original_items = local_web.ITEMS
            original_candidates = local_web.CANDIDATES
            original_fulltext_dir = local_web.fulltext_store.FULLTEXT_DIR
            local_web.ITEMS = items_path
            local_web.CANDIDATES = candidates_path
            local_web.fulltext_store.FULLTEXT_DIR = Path(tmp) / "fulltext"
            local_web.fulltext_store._STORE_CACHE.clear()
            try:
                handler = local_web.Handler.__new__(local_web.Handler)
                cleared = handler._clear_edited_markdown("item-test", "clear test")
                record = local_web.load_jsonl(items_path)[0]
                local_web.fulltext_store.hydrate_item(record)
                metadata = record["reading_metadata"]
            finally:
                local_web.ITEMS = original_items
                local_web.CANDIDATES = original_candidates
                local_web.fulltext_store.FULLTEXT_DIR = original_fulltext_dir
                local_web.fulltext_store._STORE_CACHE.clear()

        self.assertTrue(cleared)
        self.assertEqual(metadata["article_markdown"], original)
        self.assertEqual(metadata["translated_article_markdown_zh"], translated)
        self.assertNotIn("edited_markdown", metadata)
        self.assertNotIn("edited_markdown_base", metadata)
        self.assertNotIn("edited_markdown_at", metadata)

    def test_update_track_record_changes_only_target_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items_path = Path(tmp) / "items.jsonl"
            candidates_path = Path(tmp) / "candidates.jsonl"
            local_web.write_jsonl(
                items_path,
                [
                    {
                        "id": "item-test",
                        "track": "digital-humanities-local-knowledge",
                        "review": {"notes": "old note"},
                    },
                    {"id": "item-other", "track": "digital-humanities-local-knowledge"},
                ],
            )
            local_web.write_jsonl(candidates_path, [{"id": "candidate-test", "track": "digital-humanities-local-knowledge"}])
            handler = local_web.Handler.__new__(local_web.Handler)

            changed = handler.update_track_record(items_path, "item-test", "open-tech-open-industry")
            invalid = handler.update_track_record(items_path, "item-test", "not-a-track")
            records = local_web.load_jsonl(items_path)
            candidates = local_web.load_jsonl(candidates_path)

        self.assertTrue(changed)
        self.assertFalse(invalid)
        self.assertEqual(records[0]["track"], "open-tech-open-industry")
        self.assertEqual(records[0]["track_metadata"]["previous_track"], "digital-humanities-local-knowledge")
        self.assertEqual(records[0]["track_metadata"]["source"], "local_web")
        self.assertIn("手動更新大分流", records[0]["review"]["notes"])
        self.assertEqual(records[1]["track"], "digital-humanities-local-knowledge")
        self.assertEqual(candidates[0]["track"], "digital-humanities-local-knowledge")


if __name__ == "__main__":
    unittest.main()
