#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_web  # noqa: E402


class PendingReviewEntriesTest(unittest.TestCase):
    def test_hides_rss_candidate_when_active_item_exists(self) -> None:
        candidate = {
            "id": "item-1",
            "status": "inbox",
            "url": "https://example.com/story?utm_source=rss",
        }
        active = {
            "id": "item-1",
            "status": "triaged",
            "url": "https://example.com/story",
            "local_decision": {"action": "accepted-for-editing"},
        }

        self.assertEqual(local_web.pending_review_entries([active], [candidate]), [])

    def test_prefers_active_inbox_item_over_duplicate_candidate(self) -> None:
        candidate = {
            "id": "item-1",
            "status": "inbox",
            "url": "https://example.com/story",
        }
        active = {
            "id": "item-1",
            "status": "inbox",
            "url": "https://example.com/story",
        }

        self.assertEqual(local_web.pending_review_entries([active], [candidate]), [("item", active)])

    def test_hides_candidate_with_same_canonical_url(self) -> None:
        candidate = {
            "id": "candidate-1",
            "status": "inbox",
            "url": "https://example.com/story?utm_campaign=newsletter#top",
        }
        active = {
            "id": "item-1",
            "status": "ready",
            "url": "https://example.com/story",
            "local_decision": {"action": "direct-pr-small-news"},
        }

        self.assertEqual(local_web.pending_review_entries([active], [candidate]), [])

    def test_update_item_decision_removes_stale_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            originals = {
                "ITEMS": local_web.ITEMS,
                "CANDIDATES": local_web.CANDIDATES,
                "REJECTED_ITEMS": local_web.REJECTED_ITEMS,
                "DISMISSED": local_web.DISMISSED,
                "REVIEW_EVENTS": local_web.REVIEW_EVENTS,
                "DECISION_DIVERGENCES": local_web.DECISION_DIVERGENCES,
            }
            local_web.ITEMS = tmp_path / "items.jsonl"
            local_web.CANDIDATES = tmp_path / "rss-candidates.jsonl"
            local_web.REJECTED_ITEMS = tmp_path / "rejected-items.jsonl"
            local_web.DISMISSED = tmp_path / "dismissed-items.jsonl"
            local_web.REVIEW_EVENTS = tmp_path / "review-events.jsonl"
            local_web.DECISION_DIVERGENCES = tmp_path / "decision-divergences.jsonl"
            try:
                local_web.write_jsonl(
                    local_web.ITEMS,
                    [{"id": "item-1", "status": "inbox", "track": "open-tech-open-industry"}],
                )
                local_web.write_jsonl(local_web.CANDIDATES, [{"id": "item-1", "status": "inbox"}])
                local_web.write_jsonl(local_web.REJECTED_ITEMS, [])
                local_web.write_jsonl(local_web.DISMISSED, [])
                local_web.write_jsonl(local_web.REVIEW_EVENTS, [])
                local_web.write_jsonl(local_web.DECISION_DIVERGENCES, [])

                handler = local_web.Handler.__new__(local_web.Handler)
                self.assertEqual(handler.update_item_decisions(["item-1"], "direct_pr"), 1)

                self.assertEqual(local_web.load_jsonl(local_web.CANDIDATES), [])
                item = local_web.load_jsonl(local_web.ITEMS)[0]
                self.assertEqual(item["status"], "ready")
                self.assertEqual(item["local_decision"]["action"], "direct-pr-small-news")
            finally:
                for name, value in originals.items():
                    setattr(local_web, name, value)


if __name__ == "__main__":
    unittest.main()
