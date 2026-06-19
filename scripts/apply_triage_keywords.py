#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from editorial_triage import build_editorial_context, evaluate_editorial_triage
from fetch_rss import DEFAULT_CANDIDATES, TRIAGE_KEYWORDS, evaluate_triage, load_json, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
ITEMS = DATABASE / "items.jsonl"
REJECTED_ITEMS = DATABASE / "rejected-items.jsonl"


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def comparable_editorial_triage(record: dict | None) -> dict:
    if not isinstance(record, dict):
        return {}
    comparable = dict(record)
    comparable.pop("generated_at", None)
    return comparable


def apply_to_records(
    records: list[dict],
    keyword_config: dict,
    editorial_context: dict,
    statuses: set[str] | None,
) -> tuple[list[dict], int, int, int, int]:
    changed = 0
    editorial_changed = 0
    keep = 0
    skip = 0
    output = []
    for record in records:
        if statuses is not None and record.get("status") not in statuses:
            output.append(record)
            continue
        updated = dict(record)
        triage = evaluate_triage(updated, keyword_config)
        if updated.get("triage") != triage:
            changed += 1
        updated["triage"] = triage
        editorial_triage = evaluate_editorial_triage(updated, keyword_config, editorial_context)
        existing_editorial = updated.get("editorial_triage") if isinstance(updated.get("editorial_triage"), dict) else {}
        if comparable_editorial_triage(existing_editorial) == comparable_editorial_triage(editorial_triage):
            editorial_triage["generated_at"] = existing_editorial.get("generated_at", editorial_triage["generated_at"])
        if existing_editorial != editorial_triage:
            editorial_changed += 1
        updated["editorial_triage"] = editorial_triage
        if triage["recommendation"] == "suggest-keep":
            keep += 1
        elif triage["recommendation"] == "suggest-skip":
            skip += 1
        output.append(updated)
    return output, changed, editorial_changed, keep, skip


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-run triage keyword matching for local candidates and inbox items.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--rejected-items", type=Path, default=REJECTED_ITEMS)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--triage-keywords", type=Path, default=TRIAGE_KEYWORDS)
    parser.add_argument("--skip-items", action="store_true", help="Do not update database/items.jsonl.")
    parser.add_argument("--skip-candidates", action="store_true", help="Do not update .cache/rss-candidates.jsonl.")
    parser.add_argument("--all-item-statuses", action="store_true", help="Update every item status instead of only inbox.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    keyword_config = load_json(args.triage_keywords)
    item_statuses = None if args.all_item_statuses else {"inbox"}
    summary: list[str] = []
    items = load_jsonl(args.items)
    rejected_items = load_jsonl(args.rejected_items)
    editorial_context = build_editorial_context([*items, *rejected_items], keyword_config)

    if not args.skip_candidates:
        candidates = load_jsonl(args.candidates)
        updated_candidates, changed, editorial_changed, keep, skip = apply_to_records(candidates, keyword_config, editorial_context, None)
        if not args.dry_run:
            write_jsonl(args.candidates, updated_candidates)
        summary.append(
            f"candidates: {len(candidates)} checked, {changed} triage changed, "
            f"{editorial_changed} editorial changed, {keep} suggest-keep, {skip} suggest-skip"
        )

    if not args.skip_items:
        updated_items, changed, editorial_changed, keep, skip = apply_to_records(items, keyword_config, editorial_context, item_statuses)
        checked = len(items) if item_statuses is None else sum(1 for item in items if item.get("status") in item_statuses)
        if not args.dry_run:
            write_jsonl(args.items, updated_items)
        summary.append(
            f"items: {checked} checked, {changed} triage changed, "
            f"{editorial_changed} editorial changed, {keep} suggest-keep, {skip} suggest-skip"
        )

    print("\n".join(summary))


if __name__ == "__main__":
    main()
