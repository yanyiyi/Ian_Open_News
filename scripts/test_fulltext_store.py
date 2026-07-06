#!/usr/bin/env python3
"""fulltext_store 的水合/脫水測試：round-trip、inline 優先、無變更不寫檔。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fulltext_store


class FulltextStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        # 把側檔目錄指到 tmp，避免碰真資料
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._orig_dir = fulltext_store.FULLTEXT_DIR
        fulltext_store.FULLTEXT_DIR = Path(self._tmp.name)
        fulltext_store._STORE_CACHE.clear()

    def tearDown(self) -> None:
        fulltext_store.FULLTEXT_DIR = self._orig_dir
        fulltext_store._STORE_CACHE.clear()
        self._tmp.cleanup()

    def make_item(self) -> dict:
        return {
            "id": "item-test0001",
            "title": "測試",
            "reading_metadata": {
                "article_markdown": "# 全文\n\n很長的內容",
                "article_text": "全文 很長的內容",
                "translated_article_markdown_zh": "# 譯文",
                "excerpt": "短摘要（不拆）",
                "fulltext_status": "ok",
            },
        }

    def test_heavy_key_rule(self) -> None:
        self.assertTrue(fulltext_store.is_heavy_key("article_markdown"))
        self.assertTrue(fulltext_store.is_heavy_key("codex_translated_article_markdown_zh"))
        self.assertTrue(fulltext_store.is_heavy_key("edited_markdown"))
        self.assertFalse(fulltext_store.is_heavy_key("excerpt"))
        self.assertFalse(fulltext_store.is_heavy_key("fulltext_status"))

    def test_dehydrate_then_hydrate_round_trip(self) -> None:
        item = self.make_item()
        original_metadata = dict(item["reading_metadata"])
        self.assertTrue(fulltext_store.dehydrate_item(item))
        # 主檔 record 只剩輕欄位
        self.assertNotIn("article_markdown", item["reading_metadata"])
        self.assertNotIn("translated_article_markdown_zh", item["reading_metadata"])
        self.assertEqual(item["reading_metadata"]["excerpt"], "短摘要（不拆）")
        # 側檔存在且 pretty-printed
        path = fulltext_store.fulltext_path("item-test0001")
        self.assertTrue(path.exists())
        self.assertIn("\n", path.read_text(encoding="utf-8"))
        # hydrate 還原完整形狀
        fulltext_store.hydrate_item(item)
        self.assertEqual(item["reading_metadata"], original_metadata)

    def test_inline_wins_over_store(self) -> None:
        item = self.make_item()
        fulltext_store.dehydrate_item(item)
        item["reading_metadata"]["article_markdown"] = "# 新版全文"
        fulltext_store.hydrate_item(item)
        self.assertEqual(item["reading_metadata"]["article_markdown"], "# 新版全文")

    def test_no_rewrite_when_unchanged(self) -> None:
        item = self.make_item()
        fulltext_store.dehydrate_item(item)
        path = fulltext_store.fulltext_path("item-test0001")
        mtime = path.stat().st_mtime_ns
        # hydrate 後再 dehydrate（內容沒變）不應重寫側檔
        fulltext_store.hydrate_item(item)
        self.assertFalse(fulltext_store.dehydrate_item(item))
        self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_updated_field_merges_into_store(self) -> None:
        item = self.make_item()
        fulltext_store.dehydrate_item(item)
        item["reading_metadata"]["edited_markdown"] = "# 人工編修版"
        self.assertTrue(fulltext_store.dehydrate_item(item))
        stored = fulltext_store.load_fulltext("item-test0001")
        self.assertEqual(stored["edited_markdown"], "# 人工編修版")
        self.assertEqual(stored["article_markdown"], "# 全文\n\n很長的內容")  # 舊欄位保留

    def test_item_without_fulltext_is_untouched(self) -> None:
        item = {"id": "item-plain", "reading_metadata": {"excerpt": "沒有全文"}}
        self.assertFalse(fulltext_store.dehydrate_item(item))
        fulltext_store.hydrate_item(item)
        self.assertEqual(item["reading_metadata"], {"excerpt": "沒有全文"})

    def test_sidecar_enabled_only_after_store_exists(self) -> None:
        self.assertFalse(fulltext_store.sidecar_enabled())
        item = self.make_item()
        self.assertTrue(fulltext_store.dehydrate_item(item))
        self.assertTrue(fulltext_store.sidecar_enabled())


if __name__ == "__main__":
    unittest.main()
