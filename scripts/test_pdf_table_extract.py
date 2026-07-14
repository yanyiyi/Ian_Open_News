#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pdf_table_extract  # noqa: E402


class PdfTableExtractTest(unittest.TestCase):
    def test_parse_region(self) -> None:
        self.assertEqual(
            pdf_table_extract.parse_region("4:9:35:52:292:320"),
            ("4", 9, (35.0, 52.0, 292.0, 320.0)),
        )

    def test_clean_table_text_removes_indent_and_page_number(self) -> None:
        raw = "\n    Table 1   \n      Cell A   Cell B   \n    3\n\n"
        self.assertEqual(
            pdf_table_extract.clean_table_text(raw, 3),
            "Table 1\n  Cell A   Cell B",
        )

    def test_parse_columns(self) -> None:
        self.assertEqual(
            pdf_table_extract.parse_columns("4:9:35,80,180,292"),
            (("4", 9), [35.0, 80.0, 180.0, 292.0]),
        )


if __name__ == "__main__":
    unittest.main()
