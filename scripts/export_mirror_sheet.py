#!/usr/bin/env python3
"""把候選佇列與進行中 items 推到私人 Google Sheet 當「單向唯讀鏡像」。

憲法級約束：
- 單向推送：這支腳本只讀本機 JSONL、只寫 Google Sheet，絕不讀回或寫回 database。
- credential 不進 repo：service account JSON 路徑從環境變數
  IAN_OPEN_NEWS_SHEET_CREDENTIAL 或 --credential 取得；
  Sheet ID 從 IAN_OPEN_NEWS_SHEET_ID 或 --sheet-id 取得。
  缺一就視為選配功能未啟用，優雅跳過（exit 0），不是錯誤。
- gspread / google-auth 未安裝時同樣提示後跳過（exit 0）。

用法：
    python3 scripts/export_mirror_sheet.py            # 推送（需憑證）
    python3 scripts/export_mirror_sheet.py --dry-run  # 不連 Google，印預覽
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = REPO_ROOT / ".cache" / "rss-candidates.jsonl"
ITEMS_PATH = REPO_ROOT / "database" / "items.jsonl"
REVIEW_EVENTS_PATH = REPO_ROOT / "database" / "review-events.jsonl"

ENV_CREDENTIAL = "IAN_OPEN_NEWS_SHEET_CREDENTIAL"
ENV_SHEET_ID = "IAN_OPEN_NEWS_SHEET_ID"

MAX_ROWS_PER_SHEET = 500

ACTIVE_ITEM_STATUSES = {
    "inbox",
    "triaged",
    "researching",
    "drafting",
    "reviewing",
    "ready",
}

CANDIDATE_SHEET_TITLE = "候選佇列"
CANDIDATE_HEADERS = [
    "captured_at",
    "標題",
    "來源",
    "track",
    "系統建議",
    "AI 一句話推薦",
    "URL",
]

ITEM_SHEET_TITLE = "進行中 items"
ITEM_HEADERS = ["status", "標題", "track", "tags", "URL", "更新時間"]


def read_jsonl(path: Path) -> list[dict]:
    """讀 JSONL；檔案不存在回空清單，壞行跳過不中斷。"""
    records: list[dict] = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def load_latest_review_times() -> dict[str, str]:
    """從 review-events 取每個 item 最後一次事件時間（best effort）。"""
    latest: dict[str, str] = {}
    for event in read_jsonl(REVIEW_EVENTS_PATH):
        item_id = event.get("item_id")
        created_at = event.get("created_at")
        if not item_id or not isinstance(created_at, str):
            continue
        if created_at > latest.get(item_id, ""):
            latest[item_id] = created_at
    return latest


def candidate_rows() -> list[list[str]]:
    rows: list[list[str]] = []
    for record in read_jsonl(CANDIDATES_PATH):
        if record.get("candidate_status") != "pending":
            continue
        triage = record.get("editorial_triage") or {}
        codex_review = triage.get("codex_review") or {}
        title = triage.get("zh_title") or record.get("title") or ""
        rows.append(
            [
                record.get("captured_at") or "",
                title,
                record.get("source_name") or "",
                record.get("track") or "",
                triage.get("recommendation_label")
                or triage.get("recommendation")
                or "",
                codex_review.get("one_line_recommendation") or "",
                record.get("url") or "",
            ]
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    return rows


def item_rows() -> list[list[str]]:
    review_times = load_latest_review_times()
    rows: list[list[str]] = []
    for record in read_jsonl(ITEMS_PATH):
        status = record.get("status")
        if status not in ACTIVE_ITEM_STATUSES:
            continue
        tags = record.get("tags") or []
        if not isinstance(tags, list):
            tags = [str(tags)]
        updated_at = (
            review_times.get(record.get("id") or "")
            or record.get("captured_at")
            or record.get("published_at")
            or ""
        )
        rows.append(
            [
                status or "",
                record.get("editorial_title") or record.get("title") or "",
                record.get("track") or "",
                ", ".join(str(tag) for tag in tags),
                record.get("url") or "",
                updated_at,
            ]
        )
    rows.sort(key=lambda row: row[5], reverse=True)
    return rows


def truncate_rows(rows: list[list[str]], sheet_title: str) -> list[list[str]]:
    if len(rows) > MAX_ROWS_PER_SHEET:
        print(
            f"「{sheet_title}」共 {len(rows)} 列，超過上限 {MAX_ROWS_PER_SHEET} 列，"
            f"只鏡像最前面 {MAX_ROWS_PER_SHEET} 列。"
        )
        return rows[:MAX_ROWS_PER_SHEET]
    return rows


def build_sheet_payload(
    headers: list[str], rows: list[list[str]], generated_at: str
) -> list[list[str]]:
    warning = (
        f"唯讀鏡像 generated_at={generated_at}；"
        "在這裡改任何格子都不會寫回系統"
    )
    payload: list[list[str]] = [[warning] + [""] * (len(headers) - 1)]
    payload.append(list(headers))
    payload.extend(rows)
    return payload


def print_preview(title: str, headers: list[str], rows: list[list[str]]) -> None:
    print(f"[dry-run]「{title}」共 {len(rows)} 列資料")
    print(f"[dry-run]   欄位：{' | '.join(headers)}")
    for row in rows[:3]:
        cells = [cell if len(cell) <= 60 else cell[:57] + "…" for cell in row]
        print(f"[dry-run]   {' | '.join(cells)}")


def push_to_sheet(
    credential_path: str,
    sheet_id: str,
    candidates: list[list[str]],
    items: list[list[str]],
    generated_at: str,
) -> None:
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print(
            "缺少 gspread / google-auth，鏡像功能未啟用，跳過（選配功能）。"
            "如需啟用請執行：pip install gspread google-auth"
        )
        raise SystemExit(0)

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file(
        credential_path, scopes=scopes
    )
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(sheet_id)

    plan = [
        (CANDIDATE_SHEET_TITLE, CANDIDATE_HEADERS, candidates),
        (ITEM_SHEET_TITLE, ITEM_HEADERS, items),
    ]
    for sheet_title, headers, rows in plan:
        payload = build_sheet_payload(headers, rows, generated_at)
        try:
            worksheet = spreadsheet.worksheet(sheet_title)
        except gspread.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=sheet_title,
                rows=max(len(payload) + 10, 50),
                cols=len(headers),
            )
        worksheet.clear()
        worksheet.update(payload, value_input_option="RAW")
        print(f"已推送「{sheet_title}」：{len(rows)} 列資料（不含警語與表頭）。")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="單向推送候選佇列與進行中 items 到私人 Google Sheet（唯讀鏡像）。"
    )
    parser.add_argument(
        "--credential",
        default=os.environ.get(ENV_CREDENTIAL, ""),
        help=f"service account JSON 路徑（預設讀環境變數 {ENV_CREDENTIAL}）",
    )
    parser.add_argument(
        "--sheet-id",
        default=os.environ.get(ENV_SHEET_ID, ""),
        help=f"Google Sheet ID（預設讀環境變數 {ENV_SHEET_ID}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不連 Google，只印列數與前 3 列預覽",
    )
    args = parser.parse_args()

    generated_at = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    candidates = truncate_rows(candidate_rows(), CANDIDATE_SHEET_TITLE)
    items = truncate_rows(item_rows(), ITEM_SHEET_TITLE)

    if args.dry_run:
        print(f"[dry-run] generated_at={generated_at}（不連 Google）")
        print_preview(CANDIDATE_SHEET_TITLE, CANDIDATE_HEADERS, candidates)
        print_preview(ITEM_SHEET_TITLE, ITEM_HEADERS, items)
        return 0

    if not args.credential or not args.sheet_id:
        print("未設定鏡像憑證，跳過（選配功能）")
        return 0

    push_to_sheet(args.credential, args.sheet_id, candidates, items, generated_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())
