#!/usr/bin/env python3
"""author_registry 的切分/正規化/雜訊判定/解析測試。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import author_registry as ar


class SplitBylinesTest(unittest.TestCase):
    def test_strong_separators(self) -> None:
        self.assertEqual(
            ar.split_bylines("廖洲棚\n曾憲立、李天申"),
            ["廖洲棚", "曾憲立", "李天申"],
        )
        self.assertEqual(
            ar.split_bylines("Chao Liu and Cooper Quintin"),
            ["Chao Liu", "Cooper Quintin"],
        )
        self.assertEqual(
            ar.split_bylines("Emma Day; Sabine Witting"),
            ["Emma Day", "Sabine Witting"],
        )

    def test_by_prefix_stripped(self) -> None:
        self.assertEqual(ar.split_bylines("by\nKrzysztof Siewicz"), ["Krzysztof Siewicz"])
        self.assertEqual(ar.split_bylines("By John Doe"), ["John Doe"])

    def test_last_first_not_split(self) -> None:
        self.assertEqual(ar.split_bylines("Moiloa, Pelonomi"), ["Moiloa, Pelonomi"])
        self.assertEqual(ar.split_bylines("Etkin, Julia S."), ["Etkin, Julia S."])

    def test_comma_multi_person(self) -> None:
        self.assertEqual(
            ar.split_bylines("Matt Burgess, Lily Hay Newman"),
            ["Matt Burgess", "Lily Hay Newman"],
        )
        self.assertEqual(
            ar.split_bylines("Michael L. Bąk, Supheakmungkol Sarin, Adrian Mak"),
            ["Michael L. Bąk", "Supheakmungkol Sarin", "Adrian Mak"],
        )

    def test_comma_affiliation_keeps_name_only(self) -> None:
        self.assertEqual(
            ar.split_bylines("Sanjeev Sharma, Field CTO at StackGen"),
            ["Sanjeev Sharma"],
        )
        self.assertEqual(
            ar.split_bylines("Dana Cazacu, Marketing Manager, VEXXHOST"),
            ["Dana Cazacu"],
        )

    def test_parenthetical_affiliations_removed(self) -> None:
        self.assertEqual(
            ar.split_bylines("Sean Chen (Red Hat) and Yanan Cao (PyTorch, Meta Platforms)"),
            ["Sean Chen", "Yanan Cao"],
        )

    def test_dedupes_parts(self) -> None:
        self.assertEqual(ar.split_bylines("Amos、Amos"), ["Amos"])

    def test_empty(self) -> None:
        self.assertEqual(ar.split_bylines(""), [])
        self.assertEqual(ar.split_bylines(None), [])


class NoiseTest(unittest.TestCase):
    def test_dates(self) -> None:
        for value in ("January 30, 2026", "August 21, 2025", "2025-03-19",
                      "19/03/2025", "2025 年 3 月"):
            self.assertTrue(ar.looks_like_noise(value), value)

    def test_oid_and_digits(self) -> None:
        self.assertTrue(ar.looks_like_noise("2.16.886.101.20003.20007.20001"))
        self.assertTrue(ar.looks_like_noise("12345"))

    def test_placeholders(self) -> None:
        for value in ("By", "by", "Authors:", "查證來源", "-"):
            self.assertTrue(ar.looks_like_noise(value), value)

    def test_urls(self) -> None:
        self.assertTrue(ar.looks_like_noise(
            "https://www.theguardian.com/profile/bruceschneier"))

    def test_long_title_grab(self) -> None:
        self.assertTrue(ar.looks_like_noise(
            "The Model Openness Framework: Promoting Completeness and Openness "
            "for Reproducibility, Transparency, and Usability in Artificial Intelligence"))

    def test_real_names_not_noise(self) -> None:
        for value in ("Stefaan Verhulst", "廖洲棚", "@ZDNET", "Open Data Watch",
                      "entreprises.gouv.fr", "May Chen"):
            self.assertFalse(ar.looks_like_noise(value), value)

    def test_authors_with_long_affiliations_not_noise(self) -> None:
        for value in (
            "André Martins (Cilium maintainer and Software Engineer, Isovalent at Cisco) "
            "and Liz Rice (Chief Open Source Officer, Isovalent at Cisco)",
            "Maryam Tavakkoli (CNCF Ambassador | Lead Cloud Engineer @ RELEX Solutions)",
            "Niki Manoledaki (Grafana Labs), Sunyanan Choochotkaew (IBM) | CNCF Ambassadors",
        ):
            self.assertFalse(ar.looks_like_noise(value), value)

    def test_title_with_and_still_noise(self) -> None:
        self.assertTrue(ar.looks_like_noise(
            "Commons-Governed Artificial Intelligence:\nA Taxonomy of Collective Governance"))

    def test_names_with_trailing_junk_rescued(self) -> None:
        # 前段是真名、尾巴是內文誤抓：整條不算雜訊，切分救回前段名字
        raw = "Lorena Aldana, Johan Oomen, Harry This paper builds on the foundational work of Open"
        self.assertFalse(ar.looks_like_noise(raw))
        self.assertEqual(ar.split_bylines(raw), ["Lorena Aldana", "Johan Oomen"])
        dash = ("Diana Todea - DevRel Engineer at VictoriaMetrics and "
                "Laura Luttmer - Principal Product Manager at Bindplane")
        self.assertEqual(ar.split_bylines(dash), ["Diana Todea", "Laura Luttmer"])


class GuessKindTest(unittest.TestCase):
    def test_person(self) -> None:
        self.assertEqual(ar.guess_kind("Stefaan Verhulst"), "person")
        self.assertEqual(ar.guess_kind("廖洲棚"), "person")

    def test_organization(self) -> None:
        self.assertEqual(ar.guess_kind("@ZDNET"), "organization")
        self.assertEqual(ar.guess_kind("entreprises.gouv.fr"), "organization")
        self.assertEqual(ar.guess_kind("ODW"), "organization")

    def test_noise(self) -> None:
        self.assertEqual(ar.guess_kind("January 30, 2026"), "noise")


class ResolveTest(unittest.TestCase):
    def test_index_and_resolve(self) -> None:
        author = ar.new_author_record("Stefaan Verhulst")
        author["byline_names"].append("Stefaan G. Verhulst")
        index = ar.build_author_index([author])
        parts = ar.split_bylines("Stefaan G. Verhulst and Andrew Young")
        resolved = ar.resolve_byline_parts(parts, index)
        self.assertEqual(resolved[0][0], "Stefaan G. Verhulst")
        self.assertEqual(resolved[0][1]["id"], author["id"])
        self.assertIsNone(resolved[1][1])

    def test_case_insensitive_match(self) -> None:
        author = ar.new_author_record("Joseph Cox")
        index = ar.build_author_index([author])
        self.assertIs(index.get(ar.normalize_byline("JOSEPH COX")), author)

    def test_item_byline_raw_prefers_original_author(self) -> None:
        item = {"author": "Cheng",
                "reading_metadata": {"original_author": "Joseph Cox"}}
        self.assertEqual(ar.item_byline_raw(item), "Joseph Cox")
        self.assertEqual(ar.item_byline_raw({"author": "Cheng"}), "Cheng")

    def test_ids_stable(self) -> None:
        self.assertEqual(ar.author_id_for("Joseph Cox"), ar.author_id_for("joseph  cox "))
        self.assertTrue(ar.author_id_for("x").startswith("author-"))
        self.assertTrue(ar.org_id_for("x").startswith("org-"))


if __name__ == "__main__":
    unittest.main()
