#!/usr/bin/env python3
"""把協作者透過 GitHub Issue（knowledge-intake 表單）的投稿匯入候選清單。

只用 Python 標準庫 + gh CLI，流程：

1. `gh issue list` 抓開著、帶 ``knowledge:inbox`` label 的 issue
   （label 對齊 ``.github/ISSUE_TEMPLATE/knowledge-intake.yml``）。
2. 解析 Issue Form body（``### 欄位標題\\n\\n值`` 結構）。
3. 轉成候選紀錄 append 到 ``.cache/rss-candidates.jsonl``，
   ``origin="contributor"``、``candidate_status="pending"``，
   並附 ``submission`` 欄位保留投稿脈絡。

去重：同 issue_number 或同 URL（含 ``.cache/rss-dismissed.jsonl`` 與
``database/items.jsonl``）不重複匯入。

用法：
    python3 scripts/import_submissions.py --dry-run
    python3 scripts/import_submissions.py --close-after-import
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from editorial_triage import build_editorial_context, evaluate_editorial_triage  # noqa: E402
from fetch_rss import (  # noqa: E402
    DEFAULT_CANDIDATES,
    DEFAULT_DISMISSED,
    DEFAULT_REJECTED_ITEMS,
    TRIAGE_KEYWORDS,
    append_jsonl,
    clean_text,
    evaluate_triage,
    load_json,
    load_jsonl,
    normalize_url_for_match,
    parse_date,
    record_duplicate_urls,
    stable_id,
)

ROOT = SCRIPTS.parent
DEFAULT_ITEMS = ROOT / "database" / "items.jsonl"

# 對齊 .github/ISSUE_TEMPLATE/knowledge-intake.yml 的 labels 與 title 前綴。
INTAKE_LABEL = "knowledge:inbox"
INTAKE_TITLE_PREFIX = "[知識候選]"

# Issue Form 欄位 label → 內部欄位名（以 knowledge-intake.yml 的 label 為準）。
FIELD_LABELS = {
    "主線": "track",
    "標題": "title",
    "原始網址": "url",
    "來源 / 網站 / 作者": "source",
    "發布日期": "published_at",
    "原文重點": "summary",
    "為什麼值得追": "why",
    "來源類型": "source_type",
    "備註與風險": "notes",
    "你的背景／和這主題的關係": "submitter_background",
}

# 表單 dropdown 選項 → track slug（見 database/taxonomy.json / CLAUDE.md 兩條主線）。
TRACK_LABEL_TO_SLUG = {
    "數位人文與在地知識建構": "digital-humanities-local-knowledge",
    "開放科技與開放產業發展": "open-tech-open-industry",
    "未分類，請協助判斷": "unclassified",
}

NO_RESPONSE = "_No response_"


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


def fetch_open_intake_issues() -> list[dict] | None:
    """抓開著的投稿 issue；gh 不可用時回 None（呼叫端優雅退出）。"""
    try:
        auth = run_gh(["auth", "status"])
    except FileNotFoundError:
        print("找不到 gh CLI，請先安裝 GitHub CLI（https://cli.github.com/）。")
        return None
    if auth.returncode != 0:
        print("gh 尚未登入（gh auth status 失敗），請先執行 `gh auth login`。")
        return None
    listed = run_gh(
        [
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            INTAKE_LABEL,
            "--limit",
            "200",
            "--json",
            "number,title,body,author,createdAt,url",
        ]
    )
    if listed.returncode != 0:
        print("gh issue list 失敗：" + clean_text(listed.stderr, 300))
        return None
    try:
        issues = json.loads(listed.stdout or "[]")
    except json.JSONDecodeError as exc:
        print(f"無法解析 gh issue list 輸出：{exc}")
        return None
    if not isinstance(issues, list):
        return []
    return issues


def parse_issue_form_body(body: str) -> dict[str, str]:
    """把 Issue Form body（### 欄位標題\\n\\n值）拆成 {內部欄位名: 值}。"""
    fields: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if current is None:
            return
        value = "\n".join(buffer).strip()
        if value == NO_RESPONSE:
            value = ""
        fields[current] = value

    for line in (body or "").splitlines():
        heading = re.match(r"^###\s+(.+?)\s*$", line)
        if heading:
            flush()
            label = heading.group(1).strip()
            current = FIELD_LABELS.get(label)
            buffer = []
            continue
        if current is not None:
            buffer.append(line)
    flush()
    return fields


def checked_options(value: str) -> list[str]:
    """抽出 checkboxes 欄位裡有勾的選項文字。"""
    options = []
    for line in (value or "").splitlines():
        match = re.match(r"^\s*-\s*\[[xX]\]\s+(.+?)\s*$", line)
        if match:
            options.append(match.group(1))
    return options


def issue_title_without_prefix(title: str) -> str:
    text = clean_text(title, 300)
    if text.startswith(INTAKE_TITLE_PREFIX):
        text = text[len(INTAKE_TITLE_PREFIX):].strip()
    return text


def normalized_captured_at(value: str) -> str:
    parsed = parse_date(clean_text(value))
    if parsed:
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def submission_record(issue: dict, fields: dict[str, str]) -> dict:
    url = clean_text(fields.get("url"))
    title = clean_text(fields.get("title"), 300) or issue_title_without_prefix(issue.get("title", ""))
    track = TRACK_LABEL_TO_SLUG.get(clean_text(fields.get("track")), "unclassified")
    issue_url = clean_text(issue.get("url"))
    author = issue.get("author") if isinstance(issue.get("author"), dict) else {}
    submitted_by = clean_text(author.get("login"))
    tags = list(dict.fromkeys(["contributor", *checked_options(fields.get("source_type", ""))]))
    notes = "協作者透過 GitHub Issue 投稿，待人工分流與審查。"
    submitter_notes = clean_text(fields.get("notes"), 600)
    if submitter_notes:
        notes += f"投稿備註與風險：{submitter_notes}"
    return {
        "id": stable_id("item", url, issue_url, title),
        "track": track,
        "status": "inbox",
        "priority": "normal",
        "title": title or "(無標題)",
        "url": url,
        "source_id": "",
        "source_name": clean_text(fields.get("source"), 160),
        "author": clean_text(fields.get("source"), 160),
        "published_at": clean_text(fields.get("published_at"), 40),
        "captured_at": normalized_captured_at(issue.get("createdAt", "")),
        "summary": clean_text(fields.get("summary"), 1200),
        "tags": tags,
        "origin": "contributor",
        "candidate_status": "pending",
        "reference": {
            "feed_url": "",
            "guid": issue_url,
            "original_url": "",
            "source_id": "",
        },
        "submission": {
            "issue_number": issue.get("number"),
            "issue_url": issue_url,
            "submitted_by": submitted_by,
            "background": clean_text(fields.get("submitter_background"), 1200),
            "reason": clean_text(fields.get("why"), 1200),
        },
        "review": {
            "angle": "",
            "structure_review": "pending",
            "line_review": "pending",
            "target_reader_review": "pending",
            "fact_check": "pending",
            "research_status": "not-started",
            "notes": notes,
        },
    }


def attach_triage(record: dict, keyword_config: dict, editorial_context: dict) -> None:
    """比照 fetch_rss.py 補 triage 與 editorial_triage；失敗就留空並註記。"""
    try:
        record["triage"] = evaluate_triage(record, keyword_config)
        record["editorial_triage"] = evaluate_editorial_triage(record, keyword_config, editorial_context)
    except Exception as exc:  # noqa: BLE001 - 初篩失敗不擋匯入
        record["triage"] = {}
        record["editorial_triage"] = {}
        review = record.setdefault("review", {})
        review["notes"] = clean_text(review.get("notes")) + f"協作者投稿，待初篩（自動初篩失敗：{exc}）。"


def known_issue_numbers(records: list[dict]) -> set[int]:
    numbers = set()
    for record in records:
        submission = record.get("submission")
        if isinstance(submission, dict) and submission.get("issue_number") is not None:
            numbers.add(submission["issue_number"])
    return numbers


def close_issue(issue_number: int, record: dict) -> None:
    comment = (
        "感謝投稿！這筆已匯入 Ian Open News 的候選清單"
        f"（候選 id：`{record['id']}`），會在人工分流後決定是否收錄。"
    )
    commented = run_gh(["issue", "comment", str(issue_number), "--body", comment])
    if commented.returncode != 0:
        print(f"  警告：issue #{issue_number} 留言失敗：{clean_text(commented.stderr, 200)}")
    closed = run_gh(["issue", "close", str(issue_number), "--reason", "completed"])
    if closed.returncode != 0:
        print(f"  警告：issue #{issue_number} 關閉失敗：{clean_text(closed.stderr, 200)}")
    else:
        print(f"  已留言並關閉 issue #{issue_number}。")


def main() -> int:
    parser = argparse.ArgumentParser(description="匯入 GitHub Issue 協作者投稿到候選清單")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--dismissed", type=Path, default=DEFAULT_DISMISSED)
    parser.add_argument("--items", type=Path, default=DEFAULT_ITEMS)
    parser.add_argument("--dry-run", action="store_true", help="只印出會匯入的紀錄，不寫檔")
    parser.add_argument(
        "--close-after-import",
        action="store_true",
        help="匯入後在 issue 留言並關閉（預設不關）",
    )
    args = parser.parse_args()

    issues = fetch_open_intake_issues()
    if issues is None:
        return 0
    if not issues:
        print(f"沒有開著、帶 {INTAKE_LABEL} label 的投稿 issue，這次匯入 0 筆。")
        return 0

    existing_candidates = load_jsonl(args.candidates)
    dismissed_candidates = load_jsonl(args.dismissed)
    existing_items = load_jsonl(args.items)
    history = [*existing_candidates, *dismissed_candidates, *existing_items]
    seen_ids = {record.get("id") for record in history if record.get("id")}
    seen_issue_numbers = known_issue_numbers(history)
    seen_urls: set[str] = set()
    for record in history:
        seen_urls |= record_duplicate_urls(record)

    keyword_config = load_json(TRIAGE_KEYWORDS)
    editorial_context = build_editorial_context(
        [*existing_items, *load_jsonl(DEFAULT_REJECTED_ITEMS)],
        keyword_config,
    )

    new_records: list[tuple[dict, dict]] = []  # (issue, record)
    skipped = 0
    for issue in issues:
        fields = parse_issue_form_body(issue.get("body", ""))
        record = submission_record(issue, fields)
        issue_number = record["submission"]["issue_number"]
        normalized_url = normalize_url_for_match(record["url"])
        if issue_number in seen_issue_numbers:
            print(f"略過 issue #{issue_number}：已匯入過（同 issue_number）。")
            skipped += 1
            continue
        if normalized_url and normalized_url in seen_urls:
            print(f"略過 issue #{issue_number}：同 URL 已在候選、不收紀錄或資料庫。")
            skipped += 1
            continue
        if record["id"] in seen_ids:
            print(f"略過 issue #{issue_number}：候選 id 重複（{record['id']}）。")
            skipped += 1
            continue
        attach_triage(record, keyword_config, editorial_context)
        new_records.append((issue, record))
        seen_ids.add(record["id"])
        if issue_number is not None:
            seen_issue_numbers.add(issue_number)
        seen_urls |= record_duplicate_urls(record)

    if not new_records:
        print(f"沒有可匯入的新投稿（略過 {skipped} 筆重複）。")
        return 0

    if args.dry_run:
        print(f"[dry-run] 會匯入 {len(new_records)} 筆（略過 {skipped} 筆重複），不寫檔：")
        for _, record in new_records:
            print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return 0

    append_jsonl(args.candidates, [record for _, record in new_records])
    print(f"已匯入 {len(new_records)} 筆到 {args.candidates}（略過 {skipped} 筆重複）。")
    for issue, record in new_records:
        print(f"  issue #{record['submission']['issue_number']} → {record['id']}：{record['title']}")
        if args.close_after_import:
            close_issue(issue.get("number"), record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
