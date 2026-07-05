#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdf_split_suggest  # noqa: E402


class PdfSplitSuggestTest(unittest.TestCase):
    def test_load_jsonl_keeps_unicode_line_separator_inside_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "items.jsonl"
            rows = [
                {"id": "item-a", "reading_metadata": {"article_text": "First\u2028Second"}},
                {"id": "item-b", "reading_metadata": {"article_text": "Third"}},
            ]
            path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )

            self.assertEqual(pdf_split_suggest.load_jsonl(path), rows)


if __name__ == "__main__":
    unittest.main()
