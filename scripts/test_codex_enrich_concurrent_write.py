#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import codex_enrich_reviews as enrich


def review(item_id: str) -> dict:
    return {
        "id": item_id,
        "zh_title": "更新後標題",
        "one_line_recommendation": "值得看",
        "reasons": ["理由一", "理由二", "理由三"],
        "summary": "摘要",
        "recommendation": "recommend-review",
        "content_kind": "needs-review",
        "confidence": "medium",
        "needs_fulltext": False,
        "note": "",
    }


class ConcurrentReviewMergeTest(unittest.TestCase):
    def test_save_reloads_latest_file_and_preserves_new_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "items.jsonl"
            enrich.write_jsonl(path, [{"id": "item-old", "title": "舊項目"}])

            # 模擬 AI 執行期間，local-web 另外收下一篇文章。
            enrich.write_jsonl(
                path,
                [
                    {"id": "item-old", "title": "舊項目", "local_decision": {"action": "accepted-for-editing"}},
                    {"id": "item-new", "title": "AI 開始後才收下的新項目"},
                ],
            )

            merged, changed = enrich.merge_reviews_into_latest(path, [review("item-old")], "codex")

            self.assertEqual(changed, 1)
            self.assertEqual([record["id"] for record in merged], ["item-old", "item-new"])
            old = merged[0]
            self.assertEqual(old["local_decision"]["action"], "accepted-for-editing")
            self.assertEqual(old["editorial_triage"]["codex_review"]["summary"], "摘要")
            on_disk = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual([record["id"] for record in on_disk], ["item-old", "item-new"])


if __name__ == "__main__":
    unittest.main()
