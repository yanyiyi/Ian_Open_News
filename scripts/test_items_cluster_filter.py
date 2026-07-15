#!/usr/bin/env python3
"""入庫建檔區單篇 AND / 分群 OR 篩選語意。"""
from __future__ import annotations

import unittest

import local_web


class ItemsClusterFilterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.item = {
            "track": "open-tech-open-industry",
            "status": "inbox",
            "tags": ["AI governance"],
            "triage": {"recommendation": "suggest-keep", "matched_keywords": ["AI governance"]},
            "license": {"name": "CC BY 4.0"},
            "title": "Open AI governance",
        }

    def test_regular_list_requires_all_active_conditions(self) -> None:
        self.assertFalse(
            local_web.item_matches_items_filters(
                self.item,
                track="open-tech-open-industry",
                recommendation="suggest-skip",
            )
        )

    def test_cluster_view_accepts_any_active_condition(self) -> None:
        self.assertTrue(
            local_web.item_matches_items_filters(
                self.item,
                track="open-tech-open-industry",
                recommendation="suggest-skip",
                match_any=True,
            )
        )

    def test_cluster_view_with_no_active_condition_matches_everything(self) -> None:
        self.assertTrue(local_web.item_matches_items_filters(self.item, match_any=True))

    def test_cluster_key_includes_run_id(self) -> None:
        first = {"editorial_triage": {"cluster": {"run_id": "run-a", "cluster_id": "cluster-01"}}}
        second = {"editorial_triage": {"cluster": {"run_id": "run-b", "cluster_id": "cluster-01"}}}
        self.assertNotEqual(local_web.item_cluster_key(first), local_web.item_cluster_key(second))


if __name__ == "__main__":
    unittest.main()
