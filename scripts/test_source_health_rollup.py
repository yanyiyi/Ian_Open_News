#!/usr/bin/env python3
"""analyze_source_health 的 bridge rollup 與 bridge-unreachable 分級測試。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from analyze_source_health import ROLLUP_FAILED_STATUSES, apply_served_via_rollup, assess_source


def make_source(idx: int, *, served_via: str = "rsshub@local", last_fetch_status: str = "failed", status: str = "active") -> dict:
    source = {
        "id": f"src-test-{idx:04d}",
        "name": f"測試來源 {idx}",
        "feed_url": f"http://127.0.0.1:1200/test/{idx}",
        "source_type": "rss",
        "status": status,
        "fetch_frequency": "daily",
        "rss_health": {"last_fetch_status": last_fetch_status},
        "health_assessment": {"level": "danger", "reason": "個別失敗"},
    }
    if served_via:
        source["served_via"] = served_via
    return source


class ServedViaRollupTest(unittest.TestCase):
    def test_group_failure_is_rolled_up_into_single_summary(self) -> None:
        sources = [make_source(i) for i in range(5)]
        lines = apply_served_via_rollup(sources)
        self.assertEqual(len(lines), 1)
        self.assertIn("rsshub@local", lines[0])
        self.assertIn("5/5", lines[0])
        for source in sources:
            assessment = source["health_assessment"]
            self.assertEqual(assessment["rollup"], {"served_via": "rsshub@local", "failed": 5, "total": 5})
            self.assertIn("整組失敗", assessment["reason"])

    def test_small_group_is_not_rolled_up(self) -> None:
        sources = [make_source(i) for i in range(2)]
        self.assertEqual(apply_served_via_rollup(sources), [])
        for source in sources:
            self.assertNotIn("rollup", source["health_assessment"])

    def test_mostly_healthy_group_is_not_rolled_up(self) -> None:
        sources = [make_source(i, last_fetch_status="ok") for i in range(4)]
        sources.append(make_source(9, last_fetch_status="failed"))
        self.assertEqual(apply_served_via_rollup(sources), [])

    def test_bridge_unreachable_counts_toward_rollup(self) -> None:
        self.assertIn("bridge-unreachable", ROLLUP_FAILED_STATUSES)
        sources = [make_source(i, last_fetch_status="bridge-unreachable") for i in range(3)]
        lines = apply_served_via_rollup(sources)
        self.assertEqual(len(lines), 1)

    def test_non_bridge_and_archived_sources_are_ignored(self) -> None:
        sources = [make_source(i, served_via="") for i in range(5)]
        sources += [make_source(10 + i, status="archived") for i in range(5)]
        self.assertEqual(apply_served_via_rollup(sources), [])


class BridgeUnreachableAssessmentTest(unittest.TestCase):
    def test_bridge_unreachable_is_watch_not_pause(self) -> None:
        source = make_source(1, last_fetch_status="bridge-unreachable")
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        assessment = assess_source(source, [], [], [], [], cutoff)
        self.assertEqual(assessment["level"], "watch")
        self.assertEqual(assessment["suggested_status"], "active")
        self.assertNotEqual(assessment["suggested_fetch_frequency"], "paused")

    def test_plain_failed_still_suggests_pause(self) -> None:
        source = make_source(1, last_fetch_status="failed")
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        assessment = assess_source(source, [], [], [], [], cutoff)
        self.assertEqual(assessment["level"], "danger")
        self.assertEqual(assessment["suggested_status"], "paused")


if __name__ == "__main__":
    unittest.main()
