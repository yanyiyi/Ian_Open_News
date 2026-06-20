#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from page_metadata import complete_item_metadata, enrich_item_metadata


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def local_decision_action(item: dict) -> str:
    decision = item.get("local_decision")
    return str((decision or {}).get("action") or "") if isinstance(decision, dict) else ""


def is_reader_item(item: dict) -> bool:
    if item.get("status") in {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}:
        return True
    return local_decision_action(item) in {"accepted-for-editing", "direct-pr-small-news", "revisit-with-personal-notes"}


def has_image(item: dict) -> bool:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    return bool(item.get("image_url") or metadata.get("image_url"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch page metadata and cover images for reading cards.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--status", action="append", default=[], help="Limit to one or more item statuses.")
    parser.add_argument("--reader-only", action="store_true", help="Only enrich items visible in the reading area.")
    parser.add_argument("--only-missing-image", action="store_true", help="Skip items that already have an image.")
    parser.add_argument("--metadata-only", action="store_true", help="Only fill local/inferred metadata fields without fetching pages.")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = load_jsonl(args.items)
    output = []
    checked = 0
    changed = 0
    failed = 0
    skipped = 0
    for item in items:
        if args.status and item.get("status") not in set(args.status):
            output.append(item)
            continue
        if args.reader_only and not is_reader_item(item):
            output.append(item)
            continue
        if args.only_missing_image and has_image(item):
            skipped += 1
            output.append(item)
            continue
        if checked >= args.limit:
            skipped += 1
            output.append(item)
            continue
        checked += 1
        prepared, prepared_change = complete_item_metadata(item)
        if args.metadata_only:
            if prepared_change:
                changed += 1
            output.append(prepared)
            continue
        updated, did_change, error = enrich_item_metadata(prepared, timeout=args.timeout)
        if error:
            failed += 1
            if prepared_change:
                changed += 1
                output.append(prepared)
            else:
                output.append(item)
            print(f"failed {item.get('id')}: {error}")
            continue
        if did_change or prepared_change:
            changed += 1
        output.append(updated)

    if not args.dry_run:
        write_jsonl(args.items, output)
    print(f"checked={checked} changed={changed} failed={failed} skipped={skipped} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
