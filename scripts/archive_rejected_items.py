#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
ITEMS = DATABASE / "items.jsonl"
REJECTED_ITEMS = DATABASE / "rejected-items.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def local_decision_action(record: dict) -> str:
    decision = record.get("local_decision")
    if not isinstance(decision, dict):
        return ""
    return str(decision.get("action") or "")


def should_archive(record: dict) -> bool:
    return local_decision_action(record) == "rejected"


def archive_record(record: dict, moved_at: str) -> dict:
    item = dict(record)
    item["status"] = "archived"
    item["priority"] = "low"
    archive = item.get("archive") if isinstance(item.get("archive"), dict) else {}
    item["archive"] = {
        **archive,
        "moved_from": "database/items.jsonl",
        "moved_to": "database/rejected-items.jsonl",
        "moved_at": moved_at,
        "purpose": "learning-rejection-patterns",
    }
    return item


def merge_archive(existing: list[dict], moved: list[dict]) -> list[dict]:
    records_by_id: dict[str, dict] = {}
    order: list[str] = []
    for record in existing:
        record_id = str(record.get("id") or "")
        if not record_id:
            continue
        records_by_id[record_id] = record
        order.append(record_id)
    for record in moved:
        record_id = str(record.get("id") or "")
        if not record_id:
            continue
        if record_id not in records_by_id:
            order.append(record_id)
        records_by_id[record_id] = record
    return [records_by_id[record_id] for record_id in order if record_id in records_by_id]


def main() -> None:
    parser = argparse.ArgumentParser(description="Move rejected records out of database/items.jsonl.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--rejected-items", type=Path, default=REJECTED_ITEMS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = load_jsonl(args.items)
    existing_rejected = load_jsonl(args.rejected_items)
    moved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kept = []
    moved = []
    for item in items:
        if should_archive(item):
            moved.append(archive_record(item, moved_at))
        else:
            kept.append(item)

    merged_rejected = merge_archive(existing_rejected, moved)
    if not args.dry_run:
        write_jsonl(args.items, kept)
        write_jsonl(args.rejected_items, merged_rejected)

    print(
        f"items: {len(items)} scanned, {len(kept)} kept, {len(moved)} moved; "
        f"rejected archive: {len(existing_rejected)} existing, {len(merged_rejected)} total"
    )


if __name__ == "__main__":
    main()
