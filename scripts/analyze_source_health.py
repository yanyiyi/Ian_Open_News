#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
SOURCES = DATABASE / "sources.jsonl"
ITEMS = DATABASE / "items.jsonl"
REJECTED_ITEMS = DATABASE / "rejected-items.jsonl"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"


def clean_text(value: object, limit: int | None = None) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"warning: skip invalid JSONL {path}:{line_number}: {exc}")
    return records


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def parse_date(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", text):
        number = float(text)
        if 20000 <= number <= 60000:
            return datetime.fromordinal(datetime(1899, 12, 30).toordinal() + int(number)).replace(tzinfo=timezone.utc)
    normalized = text.replace("Z", "+00:00").replace("/", "-")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def record_date(record: dict) -> datetime | None:
    for key in ["dismissed_at", "captured_at", "published_at"]:
        parsed = parse_date(record.get(key))
        if parsed:
            return parsed
    return None


def is_reader_item(item: dict) -> bool:
    decision = item.get("local_decision") if isinstance(item.get("local_decision"), dict) else {}
    if decision.get("action") in {"accepted-for-editing", "direct-pr-small-news", "revisit-with-personal-notes"}:
        return True
    return item.get("status") in {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}


def source_records(records: list[dict], source_id: str) -> list[dict]:
    return [record for record in records if record.get("source_id") == source_id]


def count_recent(records: list[dict], cutoff: datetime) -> int:
    return sum(1 for record in records if (record_date(record) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff)


def assess_source(source: dict, items: list[dict], rejected: list[dict], candidates: list[dict], dismissed: list[dict], cutoff: datetime) -> dict:
    source_id = source.get("id", "")
    source_items = source_records(items, source_id)
    source_rejected = source_records(rejected, source_id)
    source_candidates = source_records(candidates, source_id)
    source_dismissed = source_records(dismissed, source_id)
    accepted_items = [item for item in source_items if is_reader_item(item)]
    inbox_items = [item for item in source_items if item.get("status") == "inbox"]
    rejected_count = len(source_rejected) + len(source_dismissed)
    recent_accepted = count_recent(accepted_items, cutoff)
    recent_rejected = count_recent([*source_rejected, *source_dismissed], cutoff)
    recent_pending = count_recent([*inbox_items, *source_candidates], cutoff)
    rss_health = source.get("rss_health") if isinstance(source.get("rss_health"), dict) else {}
    duplicate_skips = int(rss_health.get("skipped_duplicate_recent") or 0)
    keyword_skips = int(rss_health.get("skipped_source_keywords") or 0)
    new_items = int(rss_health.get("new_items") or 0)
    last_fetch_status = clean_text(rss_health.get("last_fetch_status"))

    if source.get("status") == "archived":
        level = "archived"
        recommendation = "已封存"
        suggested_status = "archived"
        suggested_frequency = source.get("fetch_frequency", "daily")
        reason = "這個來源已封存，不列入追蹤建議。"
    elif last_fetch_status == "failed":
        level = "danger"
        recommendation = "檢查或暫停來源"
        suggested_status = "paused"
        suggested_frequency = "paused"
        reason = clean_text(rss_health.get("last_error"), 160) or "最近一次 RSS 抓取失敗。"
    elif recent_rejected >= 5 and recent_rejected >= max(recent_accepted * 2, 3):
        level = "danger"
        recommendation = "建議暫停或刪除"
        suggested_status = "paused"
        suggested_frequency = "paused"
        reason = f"近 30 天不收 {recent_rejected} 則，明顯高於收下 {recent_accepted} 則。"
    elif keyword_skips >= 10 and keyword_skips >= max(new_items * 3, 10):
        level = "watch"
        recommendation = "調整個別關鍵字"
        suggested_status = source.get("status", "active")
        suggested_frequency = "weekly"
        reason = f"最近抓取有 {keyword_skips} 則被來源關鍵字擋下，可能需要放寬或改寫。"
    elif duplicate_skips >= 10 and new_items <= 2:
        level = "watch"
        recommendation = "降低抓取頻率"
        suggested_status = source.get("status", "active")
        suggested_frequency = "weekly"
        reason = f"最近抓取有 {duplicate_skips} 則是近 7 天重複網址，新資料偏少。"
    elif recent_accepted >= 5 and recent_accepted >= recent_rejected:
        level = "healthy"
        recommendation = "維持每日抓"
        suggested_status = source.get("status", "active")
        suggested_frequency = "daily"
        reason = f"近 30 天收下 {recent_accepted} 則，仍是有效來源。"
    elif recent_accepted == 0 and recent_rejected == 0 and recent_pending == 0:
        level = "new"
        recommendation = "先每週觀察"
        suggested_status = source.get("status", "active")
        suggested_frequency = "weekly"
        reason = "近期沒有足夠資料判斷，先降低頻率觀察。"
    else:
        level = "watch"
        recommendation = "維持觀察"
        suggested_status = source.get("status", "active")
        suggested_frequency = source.get("fetch_frequency", "daily")
        reason = f"近 30 天收下 {recent_accepted}、待整理 {recent_pending}、不收 {recent_rejected}。"

    rejected_reasons = Counter()
    for record in [*source_rejected, *source_dismissed]:
        decision = record.get("local_decision") if isinstance(record.get("local_decision"), dict) else {}
        reason_text = clean_text(decision.get("reason") or record.get("reason"), 100)
        if reason_text:
            rejected_reasons[reason_text] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": "local-source-health-v1",
        "level": level,
        "recommendation": recommendation,
        "reason": reason,
        "suggested_status": suggested_status,
        "suggested_fetch_frequency": suggested_frequency,
        "window_days": 30,
        "counts": {
            "accepted_total": len(accepted_items),
            "rejected_total": rejected_count,
            "pending_total": len(inbox_items) + len(source_candidates),
            "accepted_recent": recent_accepted,
            "rejected_recent": recent_rejected,
            "pending_recent": recent_pending,
            "duplicate_skips_last_fetch": duplicate_skips,
            "keyword_skips_last_fetch": keyword_skips,
        },
        "top_rejected_reasons": [reason for reason, _ in rejected_reasons.most_common(5)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Update per-RSS-source health assessment metadata.")
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--rejected-items", type=Path, default=REJECTED_ITEMS)
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--dismissed", type=Path, default=DISMISSED)
    parser.add_argument("--recent-days", type=int, default=30)
    parser.add_argument("--apply-suggested-frequency", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sources = load_jsonl(args.sources)
    items = load_jsonl(args.items)
    rejected = load_jsonl(args.rejected_items)
    candidates = load_jsonl(args.candidates)
    dismissed = load_jsonl(args.dismissed)
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.recent_days)
    updated_sources = []
    summary = Counter()
    for source in sources:
        updated = dict(source)
        assessment = assess_source(source, items, rejected, candidates, dismissed, cutoff)
        updated["health_assessment"] = assessment
        if args.apply_suggested_frequency:
            updated["fetch_frequency"] = assessment["suggested_fetch_frequency"]
        updated_sources.append(updated)
        summary[assessment["level"]] += 1

    if not args.dry_run:
        write_jsonl(args.sources, updated_sources)

    print(f"sources checked: {len(sources)}")
    for level, count in summary.most_common():
        print(f"{level}: {count}")
    print("suggestions updated in database/sources.jsonl" if not args.dry_run else "dry run only")


if __name__ == "__main__":
    main()
