#!/usr/bin/env python3
"""清理 items.jsonl 裡明顯錯誤的 author / original_author 值。

清理三類（只清「明顯錯值」，可疑但可能是真名的一律不動）：
1. 收錄者名（Cheng/YH/Amos）：來自舊 Excel「收錄者」欄，不是原作者。
   條件收緊到「author 等於收錄者名，且 reference.raw_columns['收錄者'] 同值」
   才清，並把名字補到 reference.collected_by 讓收錄人仍可查（raw_columns 也
   保留原值，provenance 不丟）。
2. 雜訊值：日期、OID、純數字、網址、佔位詞（By/Authors:/查證來源…）、
   過長的標題誤抓 —— 用 author_registry.looks_like_noise 判定。
3. author 或 original_author 等於文章標題（byline regex 誤抓整條標題）。

不動 license.*（rights_holder 是衍生欄位，另案），不動 fulltext 側檔。
逐行處理：沒改到的行原樣寫回，git diff 只會出現真的動過的行。

用法：
    python3 scripts/clean_author_noise.py            # dry-run，只印報告
    python3 scripts/clean_author_noise.py --apply    # 實際寫回
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import author_registry as ar

ITEMS_PATH = ar.ROOT / "database" / "items.jsonl"


def clean_record(record: dict, report: list[dict]) -> bool:
    """就地清理一筆 item，回傳是否有改動。"""
    changed = False
    item_id = record.get("id", "?")
    title = str(record.get("title") or "").strip()
    author = str(record.get("author") or "").strip()
    metadata = record.get("reading_metadata")
    original = ""
    if isinstance(metadata, dict):
        original = str(metadata.get("original_author") or "").strip()

    raw_columns = (record.get("reference") or {}).get("raw_columns") or {}
    collector = str(raw_columns.get("收錄者") or "").strip()

    def log(field: str, value: str, reason: str) -> None:
        report.append({"id": item_id, "field": field, "value": value, "reason": reason})

    # 1. 收錄者名被當作者
    if author and author in ar.KNOWN_COLLECTOR_NAMES and author == collector:
        record["author"] = ""
        reference = record.setdefault("reference", {})
        if isinstance(reference, dict) and not reference.get("collected_by"):
            reference["collected_by"] = author
        log("author", author, "收錄者名（搬到 reference.collected_by）")
        changed = True
        author = ""
    if original and original in ar.KNOWN_COLLECTOR_NAMES and original == collector:
        metadata["original_author"] = ""
        log("reading_metadata.original_author", original, "收錄者名")
        changed = True
        original = ""

    # 2. 雜訊值（日期/OID/網址/佔位詞/標題誤抓）＋ 3. 等於文章標題
    if author and (ar.looks_like_noise(author) or author == title):
        reason = "等於文章標題" if author == title and not ar.looks_like_noise(author) else "雜訊值"
        record["author"] = ""
        log("author", author, reason)
        changed = True
    if original and (ar.looks_like_noise(original) or original == title):
        reason = "等於文章標題" if original == title and not ar.looks_like_noise(original) else "雜訊值"
        metadata["original_author"] = ""
        log("reading_metadata.original_author", original, reason)
        changed = True

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="實際寫回（預設 dry-run）")
    args = parser.parse_args()

    report: list[dict] = []
    output_lines: list[str] = []
    changed_count = 0
    with ITEMS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if clean_record(record, report):
                changed_count += 1
                output_lines.append(json.dumps(record, ensure_ascii=False))
            else:
                output_lines.append(stripped)

    by_reason: dict[str, int] = {}
    for entry in report:
        by_reason[entry["reason"]] = by_reason.get(entry["reason"], 0) + 1
    print(f"受影響 item：{changed_count} 筆、清理欄位 {len(report)} 處")
    for reason, count in sorted(by_reason.items(), key=lambda pair: -pair[1]):
        print(f"  - {reason}: {count}")
    print()
    for entry in report:
        value = entry["value"] if len(entry["value"]) <= 80 else entry["value"][:77] + "..."
        print(f"{entry['id']}  {entry['field']}  [{entry['reason']}]  {value!r}")

    if not args.apply:
        print("\n（dry-run，未寫回；確認後加 --apply）")
        return 0

    with ITEMS_PATH.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(output_lines) + "\n")
    print(f"\n已寫回 {ITEMS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
