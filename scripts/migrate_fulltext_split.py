#!/usr/bin/env python3
"""一次性遷移：把 items.jsonl / rejected-items.jsonl 的全文重欄位拆到 database/fulltext/。

可逆：--revert 會把側檔內容併回主檔並刪掉側檔。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fulltext_store import (  # noqa: E402
    FULLTEXT_DIR,
    dehydrate_item,
    hydrate_item,
    is_heavy_key,
    load_fulltext,
    fulltext_path,
)

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "database" / "items.jsonl", ROOT / "database" / "rejected-items.jsonl"]


def load_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dump_lines(path: Path, records: list[dict]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records)
    path.write_text(text, encoding="utf-8")


def survey(records: list[dict]) -> tuple[int, int]:
    carriers = 0
    heavy_bytes = 0
    for record in records:
        metadata = record.get("reading_metadata")
        if not isinstance(metadata, dict):
            continue
        heavy = {k: v for k, v in metadata.items() if is_heavy_key(k) and v}
        if heavy:
            carriers += 1
            heavy_bytes += len(json.dumps(heavy, ensure_ascii=False))
    return carriers, heavy_bytes


def apply_split(dry_run: bool) -> int:
    total_written = 0
    for target in TARGETS:
        records = load_lines(target)
        carriers, heavy_bytes = survey(records)
        before = target.stat().st_size if target.exists() else 0
        print(f"{target.name}: {len(records)} 筆，其中 {carriers} 筆帶全文（約 {heavy_bytes/1e6:.1f}MB）")
        if dry_run:
            continue
        written = 0
        for record in records:
            if dehydrate_item(record):
                written += 1
        dump_lines(target, records)
        after = target.stat().st_size
        print(f"  → 側檔寫出 {written} 篇；主檔 {before/1e6:.1f}MB → {after/1e6:.1f}MB")
        total_written += written
    if dry_run:
        print("（dry-run：沒有寫任何檔案）")
    return total_written


def revert() -> None:
    for target in TARGETS:
        records = load_lines(target)
        restored = 0
        for record in records:
            item_id = str(record.get("id") or "")
            if load_fulltext(item_id):
                hydrate_item(record)
                restored += 1
        dump_lines(target, records)
        print(f"{target.name}: 併回 {restored} 篇全文")
    removed = 0
    for target in TARGETS:
        for record in load_lines(target):
            path = fulltext_path(str(record.get("id") or ""))
            if path and path.exists():
                path.unlink()
                removed += 1
    print(f"刪除側檔 {removed} 個")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只盤點不動檔案")
    mode.add_argument("--apply", action="store_true", help="執行拆分")
    mode.add_argument("--revert", action="store_true", help="把側檔併回主檔並刪除側檔")
    args = parser.parse_args()
    if args.revert:
        revert()
        return 0
    apply_split(dry_run=args.dry_run)
    if args.apply:
        print(f"側檔目錄：{FULLTEXT_DIR}")
        print("接著請跑 python3 scripts/validate_database.py 驗證。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
