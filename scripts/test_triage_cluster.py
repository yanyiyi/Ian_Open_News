#!/usr/bin/env python3
"""triage_cluster 的純函式測試：schema 防線、回寫最小化、全集不變式。"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import triage_cluster
from triage_cluster import apply_cluster_to_records, cluster_pool, validate_and_normalize


def payload_fixture() -> dict:
    return {
        "clusters": [
            {
                "cluster_id": "cluster-01",
                "label": "開放資料授權",
                "angle_hint": "從授權條款吵架看台灣落地",
                "member_ids": ["item-a", "item-b", "item-hallucinated"],
                "suggested_action": "collect-as-theme",
                "merge_target_item_id": "",
                "rationale": "同一場授權辯論的三個回合",
                "confidence": "high",
                "members": [
                    {"id": "item-a", "reading_depth": "deep-read", "role_in_cluster": "anchor", "one_line": "核心"},
                    {"id": "item-b", "reading_depth": "news-brief", "role_in_cluster": "support", "one_line": "補充"},
                    {"id": "item-hallucinated", "reading_depth": "deep-read", "role_in_cluster": "anchor", "one_line": "幻覺"},
                ],
            },
            {
                "cluster_id": "cluster-02",
                "label": "地方記憶庫",
                "angle_hint": "",
                "member_ids": ["item-c"],
                "suggested_action": "merge-into-item",
                "merge_target_item_id": "item-not-an-anchor",
                "rationale": "像是某稿的補充",
                "confidence": "medium",
                "members": [
                    {"id": "item-c", "reading_depth": "bogus-depth", "role_in_cluster": "weird", "one_line": ""}
                ],
            },
        ],
        "ungrouped_ids": ["item-d"],
        "notes": "",
    }


INPUT_IDS = ["item-a", "item-b", "item-c", "item-d", "item-e"]


class ValidateNormalizeTest(unittest.TestCase):
    def test_hallucinated_member_ids_are_dropped(self) -> None:
        result = validate_and_normalize(payload_fixture(), INPUT_IDS, set())
        all_members = [m for c in result["clusters"] for m in c["member_ids"]]
        self.assertNotIn("item-hallucinated", all_members)

    def test_union_of_clusters_and_ungrouped_equals_input(self) -> None:
        result = validate_and_normalize(payload_fixture(), INPUT_IDS, set())
        clustered = {m for c in result["clusters"] for m in c["member_ids"]}
        self.assertEqual(clustered | set(result["ungrouped_ids"]), set(INPUT_IDS))
        self.assertEqual(clustered & set(result["ungrouped_ids"]), set())
        # 模型漏掉的 item-e 必須被補進 ungrouped
        self.assertIn("item-e", result["ungrouped_ids"])

    def test_duplicate_membership_keeps_first_cluster_only(self) -> None:
        payload = payload_fixture()
        payload["clusters"][1]["member_ids"].append("item-a")
        payload["clusters"][1]["members"].append(
            {"id": "item-a", "reading_depth": "news-brief", "role_in_cluster": "support", "one_line": ""}
        )
        result = validate_and_normalize(payload, INPUT_IDS, set())
        occurrences = sum(c["member_ids"].count("item-a") for c in result["clusters"])
        self.assertEqual(occurrences, 1)
        self.assertIn("item-a", result["clusters"][0]["member_ids"])

    def test_merge_target_outside_whitelist_downgrades_to_ask(self) -> None:
        result = validate_and_normalize(payload_fixture(), INPUT_IDS, {"item-real-anchor"})
        cluster = next(c for c in result["clusters"] if "item-c" in c["member_ids"])
        self.assertEqual(cluster["suggested_action"], "ask")
        self.assertEqual(cluster["merge_target_item_id"], "")

    def test_merge_target_in_whitelist_is_kept(self) -> None:
        payload = payload_fixture()
        payload["clusters"][1]["merge_target_item_id"] = "item-real-anchor"
        result = validate_and_normalize(payload, INPUT_IDS, {"item-real-anchor"})
        cluster = next(c for c in result["clusters"] if "item-c" in c["member_ids"])
        self.assertEqual(cluster["suggested_action"], "merge-into-item")
        self.assertEqual(cluster["merge_target_item_id"], "item-real-anchor")

    def test_invalid_enums_fall_back_to_safe_values(self) -> None:
        result = validate_and_normalize(payload_fixture(), INPUT_IDS, set())
        member_c = next(
            m for c in result["clusters"] for m in c["members"] if m["id"] == "item-c"
        )
        self.assertEqual(member_c["reading_depth"], "knowledge-worthy")
        self.assertEqual(member_c["role_in_cluster"], "support")


class ApplyClusterTest(unittest.TestCase):
    def test_writeback_only_touches_editorial_triage_cluster(self) -> None:
        result = validate_and_normalize(payload_fixture(), INPUT_IDS, set())
        records = [
            {"id": "item-a", "title": "A", "status": "inbox", "editorial_triage": {"recommendation": "suggest-review"}},
            {"id": "item-x", "title": "X", "status": "inbox"},
        ]
        before = copy.deepcopy(records)
        updated = apply_cluster_to_records(result, records, "clu-test", "2026-07-05T00:00:00+00:00")
        self.assertEqual(updated, 1)
        # item-a 只多了 editorial_triage.cluster，其他欄位原封不動
        record_a = records[0]
        cluster_info = record_a["editorial_triage"].pop("cluster")
        self.assertEqual(record_a, before[0])
        self.assertEqual(cluster_info["run_id"], "clu-test")
        self.assertEqual(cluster_info["reading_depth"], "deep-read")
        self.assertEqual(cluster_info["label"], "開放資料授權")
        # 不在任何群的 record 完全不動
        self.assertEqual(records[1], before[1])


class ClusterPoolTest(unittest.TestCase):
    def test_pool_matches_intake_visibility_and_excludes_active_duplicate(self) -> None:
        active = {
            "id": "item-active",
            "url": "https://example.test/already-in-items",
            "status": "triaged",
        }
        hidden_candidate = {
            "id": "candidate-hidden",
            "url": "https://example.test/already-in-items",
            "candidate_status": "pending",
        }
        visible_candidate = {
            "id": "candidate-visible",
            "url": "https://example.test/still-pending",
            "candidate_status": "pending",
        }

        self.assertEqual(
            cluster_pool([active], [hidden_candidate, visible_candidate]),
            [visible_candidate],
        )

    def test_main_snapshot_uses_unified_pool_counts(self) -> None:
        candidate = {
            "id": "candidate-visible",
            "url": "https://example.test/candidate",
            "candidate_status": "pending",
        }
        inbox = {
            "id": "item-inbox",
            "url": "https://example.test/inbox",
            "status": "inbox",
        }
        payload = {
            "clusters": [],
            "ungrouped_ids": [candidate["id"], inbox["id"]],
            "notes": "",
        }

        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "triage-clusters-preview.json"

            def fake_load(path: Path) -> list[dict]:
                if path == triage_cluster.CANDIDATES:
                    return [candidate]
                if path == triage_cluster.ITEMS:
                    return [inbox]
                return []

            with patch.object(triage_cluster, "load_jsonl", side_effect=fake_load), \
                 patch.object(triage_cluster, "cluster_pool", return_value=[candidate, inbox]), \
                 patch.object(triage_cluster, "run_engine", return_value=("codex", payload)), \
                 patch.object(triage_cluster, "CLUSTERS_PREVIEW", preview), \
                 patch.object(sys, "argv", ["triage_cluster.py", "--dry-run"]):
                self.assertEqual(triage_cluster.main(), 0)

            snapshot = json.loads(preview.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["input_scope"]["pending"], 1)
            self.assertEqual(snapshot["input_scope"]["inbox"], 1)
            self.assertEqual(snapshot["input_scope"]["clustered"], 2)


class CodexCompatibilityRetryTest(unittest.TestCase):
    def test_newer_cli_error_retries_same_batch_with_compatible_model(self) -> None:
        calls: list[list[str]] = []
        result_payload = {"clusters": [], "ungrouped_ids": ["item-a"], "notes": "ok"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
                calls.append(list(command))
                if len(calls) == 1:
                    return SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr="The 'gpt-5.6-luna' model requires a newer version of Codex.",
                    )
                output_path = root / ".cache" / "triage-cluster-output.json"
                output_path.write_text(json.dumps(result_payload), encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            args = SimpleNamespace(model="", timeout=10)
            with patch.object(triage_cluster, "ROOT", root), \
                 patch.object(triage_cluster, "codex_path", return_value="codex"), \
                 patch.object(triage_cluster, "task_model", return_value="gpt-5.6-luna"), \
                 patch.object(triage_cluster.subprocess, "run", side_effect=fake_run):
                result = triage_cluster.run_codex("prompt", args)

        self.assertEqual(result_payload, result)
        self.assertEqual(2, len(calls))
        first_model_index = calls[0].index("-m") + 1
        second_model_index = calls[1].index("-m") + 1
        self.assertEqual("gpt-5.6-luna", calls[0][first_model_index])
        self.assertEqual("gpt-5.4-mini", calls[1][second_model_index])


if __name__ == "__main__":
    unittest.main()
