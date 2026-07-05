#!/usr/bin/env python3
"""套用 database/system-change-proposals.jsonl 裡已核可（status=approved）的設定提案。

只處理 operation 合法的提案：對 database/taste-profile.json 或
database/triage-keywords.json 做 append（去重）/ remove（容錯）/ set，
依檔案既有欄位慣例 bump version 與 updated_at，並把提案改成
status="done" + applied_at。重跑同一批 id 不會重複套用（idempotent）。

用法：
  python3 scripts/apply_taste_proposals.py --id prop-xxxxxxxx [--id ...]
  python3 scripts/apply_taste_proposals.py --all-approved
  加 --dry-run 只看 diff 摘要不寫檔。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taste_retro import (  # noqa: E402
    DATABASE,
    DEFAULT_PROPOSALS_FILE,
    proposal_target_file,
    resolve_dot_path,
    validate_operation,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_jsonl_lines(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_json(path: Path, doc: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def value_in_list(node: list, value: Any) -> bool:
    if value in node:
        return True
    if isinstance(value, dict) and value.get("beat"):
        return any(isinstance(entry, dict) and entry.get("beat") == value["beat"] for entry in node)
    return False


def apply_operation(doc: dict[str, Any], operation: dict[str, Any]) -> str:
    """套用單一 operation，回傳結果標籤。呼叫前應先 validate_operation。"""
    action = operation["action"]
    path = operation["path"]
    value = operation["value"]
    parts = path.split(".")
    if action == "set":
        parent = resolve_dot_path(doc, ".".join(parts[:-1])) if len(parts) > 1 else doc
        if parent.get(parts[-1]) == value:
            return "unchanged"
        parent[parts[-1]] = value
        return "set"
    node = resolve_dot_path(doc, path)
    if action == "append":
        if value_in_list(node, value):
            return "skipped-duplicate"
        node.append(value)
        return "appended"
    # remove：容錯，找不到就 not-found
    if value in node:
        node.remove(value)
        return "removed"
    if isinstance(value, str):
        for entry in node:
            if isinstance(entry, dict) and entry.get("beat") == value:
                node.remove(entry)
                return "removed"
    return "not-found"


def bump_file_meta(doc: dict[str, Any]) -> None:
    """依檔案既有欄位慣例 bump：有 version 就 +1、有 updated_at 就更新。"""
    if isinstance(doc.get("version"), int):
        doc["version"] += 1
    if "updated_at" in doc:
        doc["updated_at"] = now_iso()


def summarize_value(value: Any, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="套用已核可（approved）的系統調整提案到設定檔。")
    parser.add_argument("--id", action="append", default=[], dest="ids", help="要套用的提案 id，可重複。")
    parser.add_argument("--all-approved", action="store_true", help="套用所有 status=approved 的提案。")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--proposals-file", type=Path, default=DEFAULT_PROPOSALS_FILE)
    parser.add_argument("--database-dir", type=Path, default=DATABASE,
                        help="設定檔目錄（測試用，預設 database/）。")
    args = parser.parse_args(argv)

    proposals = load_jsonl_lines(args.proposals_file)
    if not proposals:
        print(f"{args.proposals_file} 沒有提案。")
        return 0

    wanted_ids = set(args.ids)
    if not wanted_ids and not args.all_approved:
        approved = [record for record in proposals if record.get("status") == "approved"]
        print("請用 --id 指定提案，或 --all-approved 套用全部。目前 approved 的提案：")
        for record in approved:
            print(f"  {record.get('id')}  [{record.get('kind')}]  {record.get('title')}")
        if not approved:
            print("  （沒有 approved 的提案）")
        return 1

    docs: dict[Path, dict[str, Any]] = {}
    changed_files: set[Path] = set()
    applied_count = 0
    skipped: list[str] = []
    diff_lines: list[str] = []

    for record in proposals:
        record_id = str(record.get("id") or "")
        if wanted_ids and record_id not in wanted_ids:
            continue
        if not wanted_ids and record.get("status") != "approved":
            continue
        if record.get("status") != "approved":
            skipped.append(f"{record_id}: status={record.get('status')!r}，只套 approved（重跑時 done 會自動跳過）。")
            continue
        operation = record.get("operation")
        target = proposal_target_file(record, args.database_dir)
        if record.get("kind") == "needs-code-change" or not isinstance(operation, dict) or target is None:
            skipped.append(f"{record_id}: 無合法 operation（kind={record.get('kind')}），需人工改程式。")
            continue
        if target not in docs:
            if not target.exists():
                skipped.append(f"{record_id}: 目標檔不存在 {target}")
                continue
            docs[target] = json.loads(target.read_text(encoding="utf-8"))
        ok, why = validate_operation(operation, docs[target])
        if not ok:
            skipped.append(f"{record_id}: operation 驗證未過（{why}）。")
            continue
        result = apply_operation(docs[target], operation)
        if result in {"appended", "removed", "set"}:
            changed_files.add(target)
        diff_lines.append(
            f"{record_id}  {target.name}  {operation['path']}  {operation['action']} "
            f"{summarize_value(operation['value'])}  → {result}"
        )
        record["status"] = "done"
        record["applied_at"] = now_iso()
        applied_count += 1

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}套用 {applied_count} 筆提案，改動設定檔 {len(changed_files)} 個。")
    if diff_lines:
        print("\ndiff 摘要：")
        for line in diff_lines:
            print(f"  {line}")
    if skipped:
        print("\n略過：")
        for line in skipped:
            print(f"  {line}")

    if not args.dry_run and applied_count:
        for target in changed_files:
            bump_file_meta(docs[target])
            write_json(target, docs[target])
        write_jsonl(args.proposals_file, proposals)

    if any(target.name == "triage-keywords.json" for target in changed_files):
        print("\n提醒：triage-keywords.json 已變更，記得跑 `python3 scripts/apply_triage_keywords.py` 重算候選與 inbox 的 triage。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
