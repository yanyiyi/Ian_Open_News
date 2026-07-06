#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_web


class PerplexityArchiveTest(unittest.TestCase):
    def test_accepts_perplexity_search_url(self) -> None:
        self.assertTrue(
            local_web.is_perplexity_url("https://www.perplexity.ai/search/c3e854dd-728e-4ea8-8e6d-df409bbf1bca")
        )

    def test_rejects_lookalike_domain(self) -> None:
        self.assertFalse(local_web.is_perplexity_url("https://notperplexity.ai/search/c3e854dd"))
        self.assertFalse(local_web.is_perplexity_url("https://perplexity.ai.evil.example/search/c3e854dd"))

    def test_write_archive_allows_url_only_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_path = local_web.write_perplexity_archive(
                session_id="sess-test",
                share_url="https://www.perplexity.ai/search/c3e854dd-728e-4ea8-8e6d-df409bbf1bca",
                body_text="本機已保留 Perplexity 分享連結，但無法直接抓取頁面內容。",
                citations=[],
                fetch_status="url-archived",
                fetch_error="HTTP Error 403: Forbidden",
                out_dir=Path(tmp),
            )

            text = out_path.read_text(encoding="utf-8")

        self.assertIn('fetch_status: "url-archived"', text)
        self.assertIn('fetch_error: "HTTP Error 403: Forbidden"', text)
        self.assertIn("https://www.perplexity.ai/search/c3e854dd-728e-4ea8-8e6d-df409bbf1bca", text)
        self.assertIn("無法直接抓取頁面內容", text)

    def test_archive_handler_saves_link_when_fetch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            redirects: list[str] = []
            handler = local_web.Handler.__new__(local_web.Handler)
            handler.redirect = redirects.append
            with patch.object(local_web, "ROOT", Path(tmp)), patch.object(
                local_web.urllib.request,
                "urlopen",
                side_effect=local_web.urllib.error.URLError("blocked"),
            ):
                handler.archive_perplexity_result(
                    {
                        "session_id": ["sess-test"],
                        "share_url": ["https://www.perplexity.ai/search/c3e854dd-728e-4ea8-8e6d-df409bbf1bca"],
                    }
                )
            archived = list((Path(tmp) / ".cache" / "perplexity-research").glob("*.md"))
            archived_text = archived[0].read_text(encoding="utf-8") if archived else ""

        self.assertEqual(redirects, ["/editor/session?id=sess-test&saved=perplexity_link_archived"])
        self.assertEqual(len(archived), 1)
        self.assertIn("url-archived", archived_text)

    def test_archive_handler_accepts_paste_without_share_url(self) -> None:
        pasted = """
政府新聞稿可支持政策宣示。[valitsus](https://valitsus.ee/en/news/prime-minister-michal-estonia-become-first-country-create-digital-identities-ai-agents)

補充報導：https://decrypt.co/371441/estonia-ai-agents-national-id
"""
        with tempfile.TemporaryDirectory() as tmp:
            redirects: list[str] = []
            handler = local_web.Handler.__new__(local_web.Handler)
            handler.redirect = redirects.append
            with patch.object(local_web, "ROOT", Path(tmp)):
                handler.archive_perplexity_result({"session_id": ["sess-test"], "pasted_text": [pasted]})
                archives = local_web.load_perplexity_archives("sess-test")

        self.assertEqual(redirects, ["/editor/session?id=sess-test&saved=perplexity_archived"])
        self.assertEqual(len(archives), 1)
        urls = {link["url"] for link in archives[0]["links"]}
        self.assertIn(
            "https://valitsus.ee/en/news/prime-minister-michal-estonia-become-first-country-create-digital-identities-ai-agents",
            urls,
        )
        self.assertIn("https://decrypt.co/371441/estonia-ai-agents-national-id", urls)
        self.assertIn("manual-paste", archives[0]["metadata"]["fetch_status"])

    def test_delete_archive_handler_removes_matching_session_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            redirects: list[str] = []
            handler = local_web.Handler.__new__(local_web.Handler)
            handler.redirect = redirects.append
            with patch.object(local_web, "ROOT", Path(tmp)):
                out_path = local_web.write_perplexity_archive(
                    session_id="sess-test",
                    share_url="https://www.perplexity.ai/search/c3e854dd-728e-4ea8-8e6d-df409bbf1bca",
                    body_text="answer",
                    citations=[],
                    fetch_status="manual-paste",
                )
                handler.delete_perplexity_archive({"session_id": ["sess-test"], "archive_file": [out_path.name]})
                exists_after_delete = out_path.exists()

        self.assertEqual(redirects, ["/editor/session?id=sess-test&saved=perplexity_deleted"])
        self.assertFalse(exists_after_delete)

    def test_delete_archive_handler_refuses_mismatched_session_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            redirects: list[str] = []
            handler = local_web.Handler.__new__(local_web.Handler)
            handler.redirect = redirects.append
            with patch.object(local_web, "ROOT", Path(tmp)):
                out_path = local_web.write_perplexity_archive(
                    session_id="sess-other",
                    share_url="https://www.perplexity.ai/search/c3e854dd-728e-4ea8-8e6d-df409bbf1bca",
                    body_text="answer",
                    citations=[],
                    fetch_status="manual-paste",
                )
                handler.delete_perplexity_archive({"session_id": ["sess-test"], "archive_file": [out_path.name]})
                exists_after_delete = out_path.exists()

        self.assertEqual(redirects, ["/editor/session?id=sess-test&error=perplexity_delete"])
        self.assertTrue(exists_after_delete)

    def test_perplexity_links_dedupe_markdown_and_bare_urls(self) -> None:
        text = """
一手來源：[valitsus](https://valitsus.ee/en/news/prime-minister-michal-estonia-become-first-country-create-digital-identities-ai-agents)
同一網址再次出現 https://valitsus.ee/en/news/prime-minister-michal-estonia-become-first-country-create-digital-identities-ai-agents.
"""

        links = local_web.perplexity_research_links(text)

        self.assertEqual(len(links), 1)
        self.assertEqual(
            links[0]["url"],
            "https://valitsus.ee/en/news/prime-minister-michal-estonia-become-first-country-create-digital-identities-ai-agents",
        )

    def test_bookmarklet_posts_current_page_back_to_session(self) -> None:
        href = local_web.perplexity_bookmarklet("sess-test", "http://127.0.0.1:8766/perplexity/archive")
        decoded = local_web.unquote(href)

        self.assertTrue(href.startswith("javascript:"))
        self.assertIn("sess-test", decoded)
        self.assertIn("http://127.0.0.1:8766/perplexity/archive", decoded)
        self.assertIn("pasted_text", decoded)
        self.assertIn("document.links", decoded)
        self.assertIn("form.submit()", decoded)

    def test_factcheck_prompt_includes_material_urls_and_source_rules(self) -> None:
        session = {
            "item_ids": ["item-redmonk"],
            "output_data": {
                "claims": [
                    {
                        "claim": "RedMonk 稱其追蹤樣本中排除 28 個封閉模型後，剩下 40 個模型一半是 Weights Available AI。",
                        "note": "需追溯 RedMonk 原文或資料集。",
                        "status": "needs-source",
                    }
                ],
                "recommended_sources": [
                    {
                        "title": "Open and Closed: The Pursuit of Frontier Models",
                        "url": "https://redmonk.com/sogrady/2026/05/15/open-ai-models/",
                        "why": "RedMonk 前文，可能含模型樣本與分類方法。",
                    }
                ],
            },
        }
        lookup = {
            "item-redmonk": {
                "id": "item-redmonk",
                "title": "The G7 on Open Source vs Open Weights",
                "url": "https://redmonk.com/sogrady/2026/06/02/g7-open-weights/",
                "source_name": "RedMonk - tecosystems",
                "summary": "The G7 document distinguishes open source AI from open weights.",
            }
        }

        prompt = local_web.build_perplexity_factcheck_prompt(session, lookup)

        self.assertIn("https://redmonk.com/sogrady/2026/06/02/g7-open-weights", prompt)
        self.assertIn("https://redmonk.com/sogrady/2026/05/15/open-ai-models", prompt)
        self.assertIn("不要用 Facebook", prompt)
        self.assertIn("先打開", prompt)
        self.assertIn("RedMonk 稱其追蹤樣本", prompt)


if __name__ == "__main__":
    unittest.main()
