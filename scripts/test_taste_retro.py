#!/usr/bin/env python3
"""taste_retro.py 與 apply_taste_proposals.py 的單元測試（全用 tmp 檔，不碰真資料庫）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_taste_proposals
import taste_retro


class NormalizeReasonTest(unittest.TestCase):
    def test_strips_auto_batch_suffix(self) -> None:
        self.assertEqual(
            taste_retro.normalize_reason("主線關聯弱（2026-06-27，自動批次處理）"),
            "主線關聯弱",
        )

    def test_plain_reason_unchanged(self) -> None:
        self.assertEqual(taste_retro.normalize_reason("活動公告/宣傳"), "活動公告/宣傳")

    def test_suffix_only_at_end(self) -> None:
        text = "（2026-06-27，自動批次處理）後面還有字"
        self.assertEqual(taste_retro.normalize_reason(text), text)

    def test_none_and_empty(self) -> None:
        self.assertEqual(taste_retro.normalize_reason(None), "")
        self.assertEqual(taste_retro.normalize_reason("  "), "")


def make_record(keywords: list[str], reason: str = "", source: str = "來源A",
                recommendation: str = "suggest-keep") -> dict:
    return {
        "id": f"item-{abs(hash((tuple(keywords), reason, source))) % 10**8:08x}",
        "title": "測試標題",
        "source_name": source,
        "local_decision": {"action": "rejected", "reason": reason} if reason else {},
        "triage": {"matched_keywords": keywords, "recommendation": recommendation},
    }


class KeepKeywordStatsTest(unittest.TestCase):
    KEYWORD_CONFIG = {
        "tracks": {
            "open-tech-open-industry": {"keep_keywords": ["開源", "開放資料"]},
        }
    }

    def test_rejected_rate_and_downgrade(self) -> None:
        # 「開源」：命中 5 筆、被拒 4 筆 → 80%，樣本 >= 5 → 降級候選
        kept = [make_record(["開源"])]
        rejected = [make_record(["開源"], reason=f"主線關聯弱{i}") for i in range(4)]
        stats = taste_retro.keep_keyword_stats(kept, rejected, self.KEYWORD_CONFIG)
        entry = stats["開源"]
        self.assertEqual(entry["total"], 5)
        self.assertEqual(entry["rejected"], 4)
        self.assertAlmostEqual(entry["rejected_rate"], 0.8)
        self.assertTrue(entry["downgrade_candidate"])

    def test_small_sample_not_downgraded(self) -> None:
        # 100% 被拒但樣本只有 2 → 不降級
        rejected = [make_record(["開放資料"], reason=f"r{i}") for i in range(2)]
        stats = taste_retro.keep_keyword_stats([], rejected, self.KEYWORD_CONFIG)
        entry = stats["開放資料"]
        self.assertEqual(entry["total"], 2)
        self.assertAlmostEqual(entry["rejected_rate"], 1.0)
        self.assertFalse(entry["downgrade_candidate"])

    def test_low_rate_not_downgraded(self) -> None:
        kept = [make_record(["開源"], source=f"s{i}") for i in range(4)]
        rejected = [make_record(["開源"], reason="r")]
        stats = taste_retro.keep_keyword_stats(kept, rejected, self.KEYWORD_CONFIG)
        self.assertFalse(stats["開源"]["downgrade_candidate"])

    def test_ignores_keywords_outside_keep_list(self) -> None:
        rejected = [make_record(["不在清單的詞"], reason="r")]
        stats = taste_retro.keep_keyword_stats([], rejected, self.KEYWORD_CONFIG)
        self.assertNotIn("不在清單的詞", stats)


class ValidateOperationTest(unittest.TestCase):
    DOC = {
        "version": 1,
        "global": {"emphasize": ["台灣脈絡"], "taiwan_context_required": True},
        "tracked_beats": [{"beat": "鐵道", "keywords": ["鐵道"]}],
    }

    def test_valid_append(self) -> None:
        ok, why = taste_retro.validate_operation(
            {"path": "global.emphasize", "action": "append", "value": "新訊號"}, self.DOC
        )
        self.assertTrue(ok, why)

    def test_missing_path_rejected(self) -> None:
        ok, why = taste_retro.validate_operation(
            {"path": "global.not_there", "action": "append", "value": "x"}, self.DOC
        )
        self.assertFalse(ok)
        self.assertIn("path 不存在", why)

    def test_append_to_non_list_rejected(self) -> None:
        ok, why = taste_retro.validate_operation(
            {"path": "global.taiwan_context_required", "action": "append", "value": "x"}, self.DOC
        )
        self.assertFalse(ok)
        self.assertIn("不是 list", why)

    def test_set_on_scalar_ok(self) -> None:
        ok, _ = taste_retro.validate_operation(
            {"path": "global.taiwan_context_required", "action": "set", "value": False}, self.DOC
        )
        self.assertTrue(ok)

    def test_bad_action_and_missing_value(self) -> None:
        ok, _ = taste_retro.validate_operation(
            {"path": "global.emphasize", "action": "replace", "value": "x"}, self.DOC
        )
        self.assertFalse(ok)
        ok, why = taste_retro.validate_operation(
            {"path": "global.emphasize", "action": "append"}, self.DOC
        )
        self.assertFalse(ok)
        self.assertIn("缺 value", why)

    def test_not_a_dict(self) -> None:
        ok, _ = taste_retro.validate_operation(None, self.DOC)
        self.assertFalse(ok)


class FinalizeProposalsTest(unittest.TestCase):
    def test_invalid_operation_downgraded_to_needs_code_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp)
            (database_dir / "taste-profile.json").write_text(
                json.dumps({"global": {"emphasize": []}}), encoding="utf-8"
            )
            raw = [{
                "kind": "taste-profile-update",
                "target_area": "taste-profile.json",
                "operation": {"path": "global.no_such_list", "action": "append", "value": "x"},
                "title": "測試提案",
                "rationale": "理由",
                "evidence": [],
                "confidence": "high",
            }]
            finalized = taste_retro.finalize_proposals(raw, "claude", "retro-test", database_dir)
            self.assertEqual(len(finalized), 1)
            proposal = finalized[0]
            self.assertEqual(proposal["kind"], "needs-code-change")
            self.assertIsNone(proposal["operation"])
            self.assertIn("驗證未過", proposal["notes"])
            self.assertTrue(proposal["id"].startswith("prop-"))
            self.assertEqual(proposal["status"], "proposed")
            self.assertEqual(proposal["source_report"], "retro-test")

    def test_valid_operation_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database_dir = Path(tmp)
            (database_dir / "triage-keywords.json").write_text(
                json.dumps({"tracks": {"t": {"keep_keywords": ["電子報"]}}}), encoding="utf-8"
            )
            raw = [{
                "kind": "triage-keywords-update",
                "target_area": "triage-keywords.json",
                "operation": {"path": "tracks.t.keep_keywords", "action": "remove", "value": "電子報"},
                "title": "降級電子報",
                "rationale": "被拒率過高",
                "evidence": [{"item_id": "item-1", "title": "t", "decision": "rejected", "reason": "r"}],
                "confidence": "medium",
            }]
            finalized = taste_retro.finalize_proposals(raw, "codex", "retro-test", database_dir)
            self.assertEqual(finalized[0]["kind"], "triage-keywords-update")
            self.assertEqual(finalized[0]["operation"]["action"], "remove")
            self.assertEqual(finalized[0]["evidence"][0]["item_id"], "item-1")


class ApplierTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.database_dir = Path(self._tmp.name)
        self.taste_profile = self.database_dir / "taste-profile.json"
        self.triage_keywords = self.database_dir / "triage-keywords.json"
        self.proposals_file = self.database_dir / "proposals.jsonl"
        self.taste_profile.write_text(json.dumps({
            "version": 1,
            "updated_at": "2026-06-01T00:00:00+00:00",
            "global": {"emphasize": ["台灣脈絡"], "taiwan_context_required": True},
            "tracked_beats": [],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.triage_keywords.write_text(json.dumps({
            "version": 1,
            "tracks": {"t": {"keep_keywords": ["電子報", "開源"]}},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_proposals(self, proposals: list[dict]) -> None:
        text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in proposals)
        self.proposals_file.write_text(text, encoding="utf-8")

    def run_apply(self, *argv: str) -> int:
        return apply_taste_proposals.main([
            "--proposals-file", str(self.proposals_file),
            "--database-dir", str(self.database_dir),
            *argv,
        ])

    def base_proposal(self, pid: str, kind: str, target: str, operation: dict) -> dict:
        return {
            "id": pid, "kind": kind, "target_area": target, "operation": operation,
            "title": f"提案 {pid}", "rationale": "r", "evidence": [], "confidence": "high",
            "notes": "", "proposed_at": "2026-07-01T00:00:00+00:00",
            "source_engine": "claude", "source_report": "retro-test", "status": "approved",
        }

    def test_three_actions_and_idempotent(self) -> None:
        self.write_proposals([
            self.base_proposal("prop-aaa00001", "taste-profile-update", "taste-profile.json",
                               {"path": "global.emphasize", "action": "append", "value": "新重點"}),
            self.base_proposal("prop-aaa00002", "triage-keywords-update", "triage-keywords.json",
                               {"path": "tracks.t.keep_keywords", "action": "remove", "value": "電子報"}),
            self.base_proposal("prop-aaa00003", "taste-profile-update", "taste-profile.json",
                               {"path": "global.taiwan_context_required", "action": "set", "value": False}),
            self.base_proposal("prop-aaa00004", "tracked-beat-add", "taste-profile.json",
                               {"path": "tracked_beats", "action": "append",
                                "value": {"beat": "AI 教育", "keywords": ["AI 教育"]}}),
        ])
        self.assertEqual(self.run_apply("--all-approved"), 0)

        profile = json.loads(self.taste_profile.read_text(encoding="utf-8"))
        keywords = json.loads(self.triage_keywords.read_text(encoding="utf-8"))
        self.assertIn("新重點", profile["global"]["emphasize"])
        self.assertNotIn("電子報", keywords["tracks"]["t"]["keep_keywords"])
        self.assertIn("開源", keywords["tracks"]["t"]["keep_keywords"])
        self.assertFalse(profile["global"]["taiwan_context_required"])
        self.assertEqual(profile["tracked_beats"][0]["beat"], "AI 教育")
        # 版本慣例：兩檔 version 都 +1，taste-profile 的 updated_at 更新
        self.assertEqual(profile["version"], 2)
        self.assertEqual(keywords["version"], 2)
        self.assertNotEqual(profile["updated_at"], "2026-06-01T00:00:00+00:00")
        # 提案改成 done + applied_at
        applied = [json.loads(line) for line in self.proposals_file.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(record["status"] == "done" for record in applied))
        self.assertTrue(all(record.get("applied_at") for record in applied))

        # 再跑一次：已是 done → 全部跳過，檔案內容不變（idempotent）
        profile_before = self.taste_profile.read_text(encoding="utf-8")
        keywords_before = self.triage_keywords.read_text(encoding="utf-8")
        self.assertEqual(self.run_apply("--all-approved"), 0)
        self.assertEqual(self.taste_profile.read_text(encoding="utf-8"), profile_before)
        self.assertEqual(self.triage_keywords.read_text(encoding="utf-8"), keywords_before)

    def test_append_dedupe_and_remove_tolerant(self) -> None:
        self.write_proposals([
            self.base_proposal("prop-bbb00001", "taste-profile-update", "taste-profile.json",
                               {"path": "global.emphasize", "action": "append", "value": "台灣脈絡"}),
            self.base_proposal("prop-bbb00002", "triage-keywords-update", "triage-keywords.json",
                               {"path": "tracks.t.keep_keywords", "action": "remove", "value": "不存在的詞"}),
        ])
        self.assertEqual(self.run_apply("--all-approved"), 0)
        profile = json.loads(self.taste_profile.read_text(encoding="utf-8"))
        self.assertEqual(profile["global"]["emphasize"].count("台灣脈絡"), 1)
        # 兩筆 operation 都沒造成實際變更 → 檔案 meta 不動
        self.assertEqual(profile["version"], 1)
        keywords = json.loads(self.triage_keywords.read_text(encoding="utf-8"))
        self.assertEqual(keywords["version"], 1)
        # 但提案仍收斂為 done
        applied = [json.loads(line) for line in self.proposals_file.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(record["status"] == "done" for record in applied))

    def test_only_selected_id_applied(self) -> None:
        self.write_proposals([
            self.base_proposal("prop-ccc00001", "taste-profile-update", "taste-profile.json",
                               {"path": "global.emphasize", "action": "append", "value": "只套這筆"}),
            self.base_proposal("prop-ccc00002", "taste-profile-update", "taste-profile.json",
                               {"path": "global.emphasize", "action": "append", "value": "不該被套"}),
        ])
        self.assertEqual(self.run_apply("--id", "prop-ccc00001"), 0)
        profile = json.loads(self.taste_profile.read_text(encoding="utf-8"))
        self.assertIn("只套這筆", profile["global"]["emphasize"])
        self.assertNotIn("不該被套", profile["global"]["emphasize"])
        applied = {record["id"]: record for record in (
            json.loads(line) for line in self.proposals_file.read_text(encoding="utf-8").splitlines()
        )}
        self.assertEqual(applied["prop-ccc00001"]["status"], "done")
        self.assertEqual(applied["prop-ccc00002"]["status"], "approved")

    def test_dry_run_writes_nothing(self) -> None:
        self.write_proposals([
            self.base_proposal("prop-ddd00001", "taste-profile-update", "taste-profile.json",
                               {"path": "global.emphasize", "action": "append", "value": "dry"}),
        ])
        profile_before = self.taste_profile.read_text(encoding="utf-8")
        proposals_before = self.proposals_file.read_text(encoding="utf-8")
        self.assertEqual(self.run_apply("--all-approved", "--dry-run"), 0)
        self.assertEqual(self.taste_profile.read_text(encoding="utf-8"), profile_before)
        self.assertEqual(self.proposals_file.read_text(encoding="utf-8"), proposals_before)

    def test_needs_code_change_skipped(self) -> None:
        proposal = self.base_proposal("prop-eee00001", "needs-code-change", "scripts/triage.py", None)
        self.write_proposals([proposal])
        self.assertEqual(self.run_apply("--all-approved"), 0)
        applied = [json.loads(line) for line in self.proposals_file.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(applied[0]["status"], "approved")  # 不動它，留給人工


if __name__ == "__main__":
    unittest.main()
