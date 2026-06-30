#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_enrich_reviews


class CodexEnrichReviewsTaiwanGuardTest(unittest.TestCase):
    def test_source_material_ignores_js_adblock_prompt(self) -> None:
        text, label, needs_fulltext = codex_enrich_reviews.source_material(
            {
                "title": "Google AI Overviews accuracy story",
                "summary": "Please enable JS and disable any ad blocker",
                "reading_metadata": {
                    "article_text": "Please enable JS and disable any ad blocker",
                    "description": "Please enable JS and disable any ad blocker",
                },
            }
        )

        self.assertEqual(text, "Google AI Overviews accuracy story")
        self.assertEqual(label, "只有標題")
        self.assertTrue(needs_fulltext)

    def test_prompt_treats_taiwan_context_as_evidence_bound(self) -> None:
        prompt = codex_enrich_reviews.build_prompt(
            [
                {
                    "id": "item-example",
                    "title": "Example AI governance article",
                    "source_text": "This article discusses AI governance.",
                }
            ],
            "codex",
        )

        self.assertNotIn("台灣切角為必要條件", prompt)
        self.assertIn("台灣脈絡防幻覺規則", prompt)
        self.assertIn("不得宣稱「台灣團隊」", prompt)

    def test_apply_reviews_sanitizes_taiwan_claims_without_source_signal(self) -> None:
        records = [
            {
                "id": "item-edb",
                "title": "EDB Postgres AI Launch",
                "url": "https://www.opensourceforu.com/2026/06/edb-postgres-ai-launch/",
                "source_name": "Open Source For You",
                "summary": "EnterpriseDB launches its agentic database platform.",
                "reading_metadata": {
                    "article_text": (
                        "EnterpriseDB launched EDB Postgres AI. The platform allows organizations "
                        "to host AI models, live data, and enterprise rules on infrastructure they own."
                    )
                },
            }
        ]
        reviews = [
            {
                "id": "item-edb",
                "zh_title": "EDB 推出 Postgres AI",
                "one_line_recommendation": "值得關注，這是資料主權與 AI agent 治理材料。",
                "reasons": [
                    "台灣團隊開發的 EDB PG AI 是少數直接在本地資料上運行 AI 代理的平台。",
                    "文章提到避免雲端 lakehouse 與供應商鎖定。",
                    "對於關注數位主權與 AI 基礎建設的讀者有參考價值。",
                ],
                "summary": "EnterpriseDB 發布代理式資料庫平台。該專案由台灣團隊開發，與國際大廠競爭。",
                "recommendation": "recommend-collect",
                "content_kind": "featured-article",
                "confidence": "high",
                "needs_fulltext": False,
                "note": "依 RSS 摘要判斷。",
            }
        ]

        changed = codex_enrich_reviews.apply_reviews(records, reviews, "ollama-twinkle")

        self.assertEqual(changed, 1)
        review = records[0]["editorial_triage"]["ollama_twinkle_review"]
        self.assertEqual(review["confidence"], "low")
        self.assertIn("taiwan_context_guard", review)
        self.assertTrue(review["taiwan_context_guard"]["fact_claim"])
        self.assertNotIn("台灣團隊", "\n".join(review["reasons"]))
        self.assertNotIn("台灣團隊", review["summary"])
        self.assertIn("防幻覺提醒", review["note"])
        self.assertNotIn("台灣團隊", records[0]["editorial_triage"]["zh_summary"])

    def test_apply_reviews_keeps_taiwan_claims_with_source_signal(self) -> None:
        records = [
            {
                "id": "item-taiwan",
                "title": "Taiwan AI governance forum",
                "url": "https://example.tw/story",
                "source_name": "Example Taiwan",
                "reading_metadata": {"article_text": "Taiwan teams discussed AI governance."},
            }
        ]
        reviews = [
            {
                "id": "item-taiwan",
                "zh_title": "台灣 AI 治理論壇",
                "one_line_recommendation": "台灣團隊討論 AI 治理，值得追蹤。",
                "reasons": ["台灣團隊是原文主角。", "有治理切角。", "可追後續政策。"],
                "summary": "原文提到台灣團隊討論 AI 治理。",
                "recommendation": "recommend-review",
                "content_kind": "needs-review",
                "confidence": "high",
                "needs_fulltext": False,
                "note": "原文有 Taiwan 訊號。",
            }
        ]

        codex_enrich_reviews.apply_reviews(records, reviews, "codex")

        review = records[0]["editorial_triage"]["codex_review"]
        self.assertNotIn("taiwan_context_guard", review)
        self.assertIn("台灣團隊", "\n".join(review["reasons"]))
        self.assertEqual(review["confidence"], "high")

    def test_apply_reviews_can_replace_existing_model_reviews(self) -> None:
        records = [
            {
                "id": "item-review",
                "title": "Original title",
                "editorial_triage": {
                    "codex_review": {"summary": "舊的怪摘要"},
                    "codex_generated_at": "2026-01-01T00:00:00+00:00",
                    "claude_review": {"summary": "另一個舊摘要"},
                    "claude_generated_at": "2026-01-01T00:00:00+00:00",
                    "zh_summary": "中文標題：舊摘要",
                },
            }
        ]
        reviews = [
            {
                "id": "item-review",
                "zh_title": "新的閱讀建議",
                "one_line_recommendation": "值得重跑後再看。",
                "reasons": ["理由一。", "理由二。", "理由三。"],
                "summary": "新的摘要。",
                "recommendation": "recommend-review",
                "content_kind": "needs-review",
                "confidence": "medium",
                "needs_fulltext": False,
                "note": "重跑。",
            }
        ]

        changed = codex_enrich_reviews.apply_reviews(records, reviews, "claude", replace_existing=True)

        editorial = records[0]["editorial_triage"]
        self.assertEqual(changed, 1)
        self.assertNotIn("codex_review", editorial)
        self.assertNotIn("codex_generated_at", editorial)
        self.assertIn("claude_review", editorial)
        self.assertEqual(editorial["zh_title"], "新的閱讀建議")
        self.assertIn("新的摘要", editorial["zh_summary"])


if __name__ == "__main__":
    unittest.main()
