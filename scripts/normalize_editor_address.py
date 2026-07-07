#!/usr/bin/env python3
"""一次性清理：把資料庫裡既有的「給 Ian／值得 Ian／Ian 可以」等對編輯喊話字樣洗掉。

背景：舊版 AI 閱讀建議 prompt 要求用「給 Ian 的一句話推薦」語氣，於是模型把
「給 Ian：」「值得 Ian 先收」寫進 one_line_recommendation；formatted_summary 也把
「給 Ian 的一句話推薦：」硬寫進 editorial_triage.zh_summary。這些是給編輯內化用的
判斷，不該出現在任何對外輸出。prompt 與 formatted_summary 已在 codex_enrich_reviews
修好（新資料乾淨），這支腳本負責把 items.jsonl / rejected-items.jsonl 的既有資料補齊。

作法：
  - 每筆 review（各 provider 的 *_review）的 one_line_recommendation / summary /
    reasons / note 都套 strip_editor_address。
  - editorial_triage.zh_summary 直接用（已改過標籤的）formatted_summary 依洗乾淨的
    review 重新產生，這樣「一句話推薦：」的區段標題會保留、只拿掉「給 Ian 的」。
  - 未變更的行原封不動保留，確保 diff 只落在真的有洗到的欄位。

預設是 dry-run（只印統計不寫檔）；確認後加 --apply 真的寫入，再跑
python3 scripts/validate_database.py 確認格式。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from codex_enrich_reviews import (
    AI_PROVIDERS,
    ITEMS,
    ROOT,
    formatted_summary,
    sanitize_review_editor_address,
    strip_editor_address,
)

REJECTED = ROOT / "database" / "rejected-items.jsonl"

REVIEW_KEYS = [meta["review_key"] for meta in AI_PROVIDERS.values()]


def _owning_review(editorial: dict) -> dict | None:
    """zh_summary 原本由哪個 review 產生：優先 codex，否則第一個有的 provider。"""
    codex = editorial.get("codex_review")
    if isinstance(codex, dict):
        return codex
    for key in REVIEW_KEYS:
        review = editorial.get(key)
        if isinstance(review, dict):
            return review
    return None


def normalize_record(record: dict) -> None:
    editorial = record.get("editorial_triage")
    if not isinstance(editorial, dict):
        return
    for key in REVIEW_KEYS:
        review = editorial.get(key)
        if isinstance(review, dict):
            sanitize_review_editor_address(review)
    if editorial.get("zh_summary"):
        owner = _owning_review(editorial)
        if isinstance(owner, dict):
            editorial["zh_summary"] = formatted_summary(owner)
        else:
            # 極少數：有 zh_summary 卻沒有 review。至少把舊標籤與稱呼洗掉。
            editorial["zh_summary"] = strip_editor_address(
                str(editorial["zh_summary"]).replace("給 Ian 的一句話推薦：", "一句話推薦：")
            )


def process_file(path: Path, apply: bool) -> tuple[int, int]:
    """回傳 (掃描筆數, 變更筆數)。未變更的行逐字保留。"""
    if not path.exists():
        return (0, 0)
    text = path.read_text(encoding="utf-8")
    out_lines: list[str] = []
    scanned = 0
    changed = 0
    for line in text.split("\n"):
        if not line.strip():
            out_lines.append(line)  # 保留空行 / 檔尾換行
            continue
        record = json.loads(line)
        scanned += 1
        before = json.dumps(record, ensure_ascii=False, sort_keys=True)
        normalize_record(record)
        after = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed += 1
            out_lines.append(after)
        else:
            out_lines.append(line)  # 逐字保留，避免無謂 diff
    if apply and changed:
        path.write_text("\n".join(out_lines), encoding="utf-8")
    return (scanned, changed)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理資料庫既有的『給 Ian』對編輯喊話字樣。")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--rejected", type=Path, default=REJECTED)
    parser.add_argument("--apply", action="store_true", help="真的寫回檔案；預設只做 dry-run。")
    args = parser.parse_args()

    total_changed = 0
    for label, path in (("items", args.items), ("rejected-items", args.rejected)):
        scanned, changed = process_file(path, args.apply)
        total_changed += changed
        print(f"{label}: 掃描 {scanned} 筆，需清理 {changed} 筆 -> {path}")

    if args.apply:
        print(f"已寫回，共清理 {total_changed} 筆。建議接著跑 python3 scripts/validate_database.py")
    else:
        print(f"[dry-run] 共 {total_changed} 筆會被清理；加 --apply 才會真的寫入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
