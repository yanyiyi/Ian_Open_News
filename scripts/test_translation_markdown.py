#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_translate_article as translate  # noqa: E402
import local_web  # noqa: E402


class TranslationMarkdownTest(unittest.TestCase):
    def test_tsv_layout_tokens_round_trip_through_protected_markers(self) -> None:
        source = "Before\n\n```tsv\nA\tB\n[continued]\n1\t2\n```\n\nAfter"

        protected = translate.protect_layout_tokens(source)
        restored = translate.restore_layout_tokens(protected)

        self.assertNotIn("\t", protected)
        self.assertEqual(protected.count(translate.TABLE_CELL_MARKER), 2)
        self.assertEqual(protected.count(translate.TABLE_CONTINUED_MARKER), 1)
        self.assertEqual(restored, source)

    def test_tsv_layout_validation_rejects_flattened_translation(self) -> None:
        source = "```tsv\nA\tB\n1\t2\n```"
        flattened = "```tsv\nA B\n1 2\n```"

        with self.assertRaisesRegex(RuntimeError, "表格結構驗證失敗"):
            translate.validate_translated_layout(source, flattened)

    def test_long_tsv_translation_is_batched_and_reassembled(self) -> None:
        rows = [f"row-{index}\tvalue-{index}" for index in range(55)]
        source = "```tsv\n" + "\n".join(rows) + "\n```"

        def echo_protected_fence(_provider: str, prompt: str, _timeout: int) -> str:
            match = translate.re.search(r"片段：\n(```tsv.*?\n```)", prompt, flags=translate.re.S)
            self.assertIsNotNone(match)
            return match.group(1)

        with patch.object(translate, "run_chunk", side_effect=echo_protected_fence) as run_chunk:
            translated = translate.translate_tsv_group(source, "en", "codex", 0, 1, 30)

        self.assertEqual(run_chunk.call_count, 3)
        self.assertEqual(translated, source)
        self.assertEqual(translate.layout_signature(translated), (1, 55, 0))

    def test_chunk_resume_reruns_only_flattened_table_chunk(self) -> None:
        markdown = "```tsv\nA\tB\n1\t2\n```"
        source_hash = translate.hashlib.sha1(markdown.encode("utf-8")).hexdigest()[:16]
        record = {
            "id": "item-table-resume",
            "title": "Table",
            "reading_metadata": {
                "translation_progress": {
                    "source_hash": source_hash,
                    "total": 1,
                    "chunks": {"0": "```tsv\n甲 乙\n一 二\n```"},
                }
            },
        }
        provider_output = (
            "```tsv\n甲"
            + translate.TABLE_CELL_MARKER
            + "乙\n一"
            + translate.TABLE_CELL_MARKER
            + "二\n```"
        )
        with patch.object(translate, "run_chunk", return_value=provider_output) as run_chunk:
            payload = translate.translate_record_chunked(
                [record], record, markdown, "en", "codex", Path("items.jsonl"),
                None, 1000, 30, True,
            )

        run_chunk.assert_called_once()
        self.assertEqual(payload["zh_markdown"].count("\t"), 2)
        self.assertEqual(payload["zh_markdown"].count("```tsv"), 1)

    def test_completed_translation_repairs_only_table_groups(self) -> None:
        markdown = "# Report\n\nIntro.\n\n```tsv\nA\tB\n1\t2\n```\n\nEnd."
        source_hash = translate.hashlib.sha1(markdown.encode("utf-8")).hexdigest()[:16]
        record = {
            "id": "item-complete-table-repair",
            "title": "Report",
            "reading_metadata": {
                "codex_translated_article_markdown_zh": "# 報告\n\n前言。\n\n```tsv\n甲 乙\n一 二\n```\n\n結尾。",
                "codex_translation_source_hash": source_hash,
                "translation_progress": {"source_hash": source_hash, "total": 1, "done": 1},
            },
        }
        provider_output = (
            "```tsv\n甲"
            + translate.TABLE_CELL_MARKER
            + "乙\n一"
            + translate.TABLE_CELL_MARKER
            + "二\n```"
        )
        with patch.object(translate, "run_chunk", return_value=provider_output) as run_chunk:
            payload = translate.translate_record_chunked(
                [record], record, markdown, "en", "codex", Path("items.jsonl"),
                None, 1000, 30, True,
            )

        run_chunk.assert_called_once()
        self.assertIn("前言。", payload["zh_markdown"])
        self.assertIn("結尾。", payload["zh_markdown"])
        self.assertEqual(payload["zh_markdown"].count("\t"), 2)
        self.assertNotIn("translation_table_repair_progress", record["reading_metadata"])

    def test_translate_status_path_is_scoped_per_item(self) -> None:
        self.assertEqual(
            local_web.translate_status_path("item/a"),
            local_web.ROOT / ".cache" / "translate-status-item-a.json",
        )
        self.assertNotEqual(
            local_web.translate_status_path("item-a"),
            local_web.translate_status_path("item-b"),
        )

    def test_background_translation_worker_writes_terminal_status(self) -> None:
        class FinishedProcess:
            returncode = 0

            def communicate(self, timeout: int):
                self.timeout = timeout
                return "translated", ""

        with tempfile.TemporaryDirectory() as tmpdir:
            status_path = Path(tmpdir) / "translate.json"
            local_web.write_json(
                status_path,
                {"state": "running", "done": 2, "total": 2, "message": "翻譯完成，共 2 段。"},
            )
            proc = FinishedProcess()
            local_web.background_translation_worker(
                "item-bg",
                proc,
                status_path,
                "/items/view?id=item-bg&saved=translation",
            )
            status = local_web.load_json(status_path)

        self.assertEqual(status["state"], "done")
        self.assertEqual(status["returncode"], 0)
        self.assertEqual(status["done"], 2)
        self.assertEqual(status["redirect"], "/items/view?id=item-bg&saved=translation")

    def test_translation_form_uses_background_job_runner(self) -> None:
        html = local_web.page("test", "<p>body</p>").decode("utf-8")

        self.assertIn('form[data-translate-form]', html)
        self.assertIn("window.runBackgroundEngineJob({", html)
        self.assertIn('data.set("background", "1")', html)

    def test_source_markdown_does_not_truncate_long_pdf(self) -> None:
        markdown = "# Long PDF\n\n" + ("Complete source paragraph. " * 5000)
        record = {"id": "item-long-pdf", "reading_metadata": {"article_markdown": markdown}}

        source = translate.source_markdown(record)

        self.assertEqual(source, translate.clean_markdown(markdown))
        self.assertGreater(len(source), 100000)

    def test_source_markdown_appends_pdf_table_sidecar(self) -> None:
        record = {"id": "item-table-test", "reading_metadata": {"article_markdown": "# Article\n\nBody."}}
        with tempfile.TemporaryDirectory() as tmpdir:
            table_dir = Path(tmpdir)
            (table_dir / "item-table-test.md").write_text("# PDF tables\n\nTable 1 repaired.", encoding="utf-8")
            with patch.object(translate, "PDF_TABLES_DIR", table_dir):
                source = translate.source_markdown(record)

        self.assertIn("# Article", source)
        self.assertIn("# PDF tables", source)
        self.assertIn("Table 1 repaired.", source)

    def test_source_markdown_preserves_fixed_width_table_columns(self) -> None:
        record = {"id": "item-table-layout", "reading_metadata": {"article_markdown": "# Article\n\nBody."}}
        with tempfile.TemporaryDirectory() as tmpdir:
            table_dir = Path(tmpdir)
            (table_dir / "item-table-layout.md").write_text(
                "## Table 1\n\n```text\nColumn A        Column B\nvalue           result\n```\n",
                encoding="utf-8",
            )
            with patch.object(translate, "PDF_TABLES_DIR", table_dir):
                source = translate.source_markdown(record)

        self.assertIn("Column A        Column B", source)
        self.assertIn("value           result", source)

    def test_source_markdown_prefers_integrated_pdf_article_without_duplicate_table_append(self) -> None:
        record = {"id": "item-integrated", "reading_metadata": {"article_markdown": "# Broken extraction"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            articles = root / "articles"
            tables = root / "tables"
            articles.mkdir()
            tables.mkdir()
            integrated = "# Complete article\n\nBefore.\n\n```tsv\nA\tB\n1\t2\n```\n\nAfter."
            (articles / "item-integrated.md").write_text(integrated, encoding="utf-8")
            (tables / "item-integrated.md").write_text("## Table 1\n\n```tsv\nA\tB\n1\t2\n```", encoding="utf-8")
            with patch.object(translate, "PDF_ARTICLES_DIR", articles), patch.object(
                translate, "PDF_TABLES_DIR", tables
            ):
                source = translate.source_markdown(record)

        self.assertEqual(source, integrated)
        self.assertEqual(source.count("```tsv"), 1)

    def test_codex_translation_model_does_not_inherit_incompatible_desktop_default(self) -> None:
        with patch.dict(translate.os.environ, {}, clear=True):
            self.assertEqual(translate.codex_translation_model(), "gpt-5.4")
        with patch.dict(translate.os.environ, {"IAN_OPEN_NEWS_CODEX_MODEL": "gpt-5.4-mini"}):
            self.assertEqual(translate.codex_translation_model(), "gpt-5.4-mini")

    def test_codex_failure_detail_extracts_api_message(self) -> None:
        stderr = 'ERROR: {"error":{"message":"The selected model requires a newer CLI."}}'
        self.assertEqual(
            translate.codex_failure_detail(stderr),
            "The selected model requires a newer CLI.",
        )

    def test_codex_env_uses_writable_runtime_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repo"
            source_home = Path(tmpdir) / "user-codex"
            source_home.mkdir(parents=True)
            (source_home / "auth.json").write_text('{"token":"test"}', encoding="utf-8")
            (source_home / "config.toml").write_text('model = "test"\n', encoding="utf-8")
            with patch.object(translate, "ROOT", root), patch.dict(
                translate.os.environ,
                {"CODEX_HOME": str(source_home)},
                clear=False,
            ):
                env = translate._codex_env()

            runtime_home = root / ".cache" / "codex-cli-home"
            self.assertEqual(env["CODEX_HOME"], str(runtime_home))
            self.assertEqual((runtime_home / "auth.json").read_text(encoding="utf-8"), '{"token":"test"}')
            self.assertTrue((runtime_home / "config.toml").exists())

    def test_chunk_plan_is_saved_before_first_provider_call(self) -> None:
        record = {"id": "item-test", "title": "Test", "reading_metadata": {}}
        markdown = "First paragraph with enough text.\n\nSecond paragraph with enough text."
        with patch.object(translate, "write_record") as write_record, patch.object(
            translate,
            "run_chunk",
            side_effect=RuntimeError("provider failed before first chunk"),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                translate.translate_record_chunked(
                    [record], record, markdown, "en", "codex", Path("items.jsonl"),
                    None, 40, 30, False,
                )

        progress = record["reading_metadata"]["translation_progress"]
        self.assertEqual(progress["total"], 2)
        self.assertEqual(progress["chunks"], {})
        write_record.assert_called_once()

    def test_codex_text_rejects_stale_output_when_cli_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache = root / ".cache"
            cache.mkdir()
            (cache / "codex-translate-chunk.txt").write_text("stale translation", encoding="utf-8")
            completed = translate.subprocess.CompletedProcess(
                ["codex"], returncode=0, stdout="", stderr="",
            )
            with patch.object(translate, "ROOT", root), patch.object(
                translate, "codex_path", return_value="codex",
            ), patch.object(translate, "_codex_env", return_value={}), patch.object(
                translate.subprocess, "run", return_value=completed,
            ):
                with self.assertRaisesRegex(RuntimeError, "without writing translation output"):
                    translate.run_codex_text("translate", 30)

    def test_codex_text_accepts_complete_tsv_from_stdout_when_output_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".cache").mkdir()
            stdout = "codex\n```tsv\n甲[[[IAN_TABLE_CELL]]]乙\n```\ntokens used\n123\n"
            completed = translate.subprocess.CompletedProcess(
                ["codex"], returncode=0, stdout=stdout, stderr="warning",
            )
            with patch.object(translate, "ROOT", root), patch.object(
                translate, "codex_path", return_value="codex",
            ), patch.object(translate, "_codex_env", return_value={}), patch.object(
                translate.subprocess, "run", return_value=completed,
            ):
                output = translate.run_codex_text("translate table", 30)

        self.assertEqual(output, "```tsv\n甲[[[IAN_TABLE_CELL]]]乙\n```")

    def test_codex_text_uses_unique_output_paths_and_cleans_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_paths: list[Path] = []

            def write_output(command: list[str], **_kwargs: object) -> translate.subprocess.CompletedProcess[str]:
                index = command.index("--output-last-message")
                output_path = Path(command[index + 1])
                output_paths.append(output_path)
                output_path.write_text(f"result-{len(output_paths)}", encoding="utf-8")
                return translate.subprocess.CompletedProcess(command, returncode=0, stdout="", stderr="")

            with patch.object(translate, "ROOT", root), patch.object(
                translate, "codex_path", return_value="codex",
            ), patch.object(translate, "_codex_env", return_value={}), patch.object(
                translate.subprocess, "run", side_effect=write_output,
            ):
                first = translate.run_codex_text("first", 30)
                second = translate.run_codex_text("second", 30)

        self.assertEqual(first, "result-1")
        self.assertEqual(second, "result-2")
        self.assertEqual(len(set(output_paths)), 2)
        self.assertTrue(all(not path.exists() for path in output_paths))

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

    def test_apply_translation_preserves_tsv_tabs(self) -> None:
        record = {"id": "item-tabs", "reading_metadata": {}}
        markdown = "# 表格\n\n```tsv\n欄一\t欄二\n值一\t值二\n```"

        translate.apply_translation(
            record,
            {"zh_title": "表格", "zh_markdown": markdown, "note": "test"},
            "en",
            "codex",
            source_hash="abc123",
        )

        stored = record["reading_metadata"]["codex_translated_article_markdown_zh"]
        self.assertEqual(stored.count("\t"), 2)
        self.assertEqual(translate.layout_signature(stored), (1, 2, 0))

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
