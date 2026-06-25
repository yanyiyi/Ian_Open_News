#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
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


def clean_text(value: object) -> str:
    return str(value or "").strip()


def image_candidates(item: dict) -> list[str]:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
    cache = metadata.get("image_cache") if isinstance(metadata.get("image_cache"), dict) else {}
    raw_columns = reference.get("raw_columns") if isinstance(reference.get("raw_columns"), dict) else {}
    cached_path = clean_text(cache.get("path"))
    cached_image = cached_path if cached_path and (ROOT / cached_path).exists() else ""
    candidates = [
        cached_image,
        item.get("image"),
        item.get("image_url"),
        item.get("thumbnail"),
        item.get("og_image"),
        metadata.get("image_url"),
        metadata.get("og_image"),
        metadata.get("twitter_image"),
        reference.get("image"),
        reference.get("image_url"),
        reference.get("thumbnail"),
        reference.get("og_image"),
        raw_columns.get("image"),
        raw_columns.get("Image"),
        raw_columns.get("圖片"),
        raw_columns.get("封面"),
    ]
    summary = clean_text(item.get("summary"))
    candidates.extend(re.findall(r"""<img[^>]+src=["']([^"']+)["']""", summary, flags=re.I))
    candidates.extend(
        re.findall(
            r"""https?://[^\s"'<>]+?\.(?:png|jpe?g|webp|gif|avif)(?:\?[^\s"'<>]*)?""",
            summary,
            flags=re.I,
        )
    )
    return [clean_text(value) for value in candidates if clean_text(value)]


def has_image(item: dict) -> bool:
    return bool(image_candidates(item))


def missing_reader_fields(item: dict) -> list[str]:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    missing = []
    if not has_image(item):
        missing.append("image")
    if not clean_text(metadata.get("description")):
        missing.append("description")
    if not clean_text(metadata.get("article_markdown") or metadata.get("article_text")):
        missing.append("article")
    return missing


def parse_datetime(value: object) -> datetime | None:
    text = clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def last_enrichment_attempt(item: dict) -> datetime | None:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    enrichment = metadata.get("reader_enrichment") if isinstance(metadata.get("reader_enrichment"), dict) else {}
    return parse_datetime(enrichment.get("last_attempt_at") or metadata.get("fetched_at"))


def retry_is_due(item: dict, now: datetime, retry_after_days: int) -> bool:
    if retry_after_days <= 0:
        return True
    last_attempt = last_enrichment_attempt(item)
    return last_attempt is None or now - last_attempt >= timedelta(days=retry_after_days)


def with_enrichment_status(
    item: dict,
    *,
    attempted_at: str,
    status: str,
    missing_fields: list[str],
    error: str = "",
) -> dict:
    updated = dict(item)
    metadata = dict(updated.get("reading_metadata") if isinstance(updated.get("reading_metadata"), dict) else {})
    previous = metadata.get("reader_enrichment") if isinstance(metadata.get("reader_enrichment"), dict) else {}
    metadata["reader_enrichment"] = {
        **previous,
        "last_attempt_at": attempted_at,
        "last_status": status,
        "missing_fields": missing_fields,
        "error": error,
        "attempt_count": int(previous.get("attempt_count") or 0) + 1,
    }
    updated["reading_metadata"] = metadata
    return updated


def item_title(item: dict) -> str:
    for key in ("title", "original_title", "source_name", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value[:120]
    return "未命名文章"


def write_status(path: Path | None, payload: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch page metadata and cover images for reading cards.")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--status", action="append", default=[], help="Limit to one or more item statuses.")
    parser.add_argument("--reader-only", action="store_true", help="Only enrich items visible in the reading area.")
    parser.add_argument("--only-missing-image", action="store_true", help="Skip items that already have an image.")
    parser.add_argument(
        "--only-missing-reader-data",
        action="store_true",
        help="Only enrich items missing an image, page description, or article body.",
    )
    parser.add_argument(
        "--retry-after-days",
        type=int,
        default=0,
        help="Do not retry incomplete or failed items until this many days after the last attempt.",
    )
    parser.add_argument("--metadata-only", action="store_true", help="Only fill local/inferred metadata fields without fetching pages.")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    items = load_jsonl(args.items)
    now = datetime.now(timezone.utc)
    status_filter = set(args.status)
    candidates = []
    cooldown = 0
    for index, item in enumerate(items):
        if status_filter and item.get("status") not in status_filter:
            continue
        if args.reader_only and not is_reader_item(item):
            continue
        if args.only_missing_image and has_image(item):
            continue
        if args.only_missing_reader_data and not missing_reader_fields(item):
            continue
        if not retry_is_due(item, now, args.retry_after_days):
            cooldown += 1
            continue
        last_attempt = last_enrichment_attempt(item)
        candidates.append((last_attempt is not None, last_attempt or datetime.min.replace(tzinfo=timezone.utc), index))

    candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    selected_indexes = [row[2] for row in candidates[: args.limit]]
    checked = 0
    changed = 0
    failed = 0
    for item_index in selected_indexes:
        item = items[item_index]
        checked += 1
        title = item_title(item)
        write_status(
            args.status_file,
            {
                "command": "enrich_reader_metadata",
                "state": "running",
                "message": "正在補閱讀卡圖片、描述與主文",
                "index": checked,
                "total": len(selected_indexes),
                "item_id": item.get("id"),
                "item_title": title,
            },
        )
        print(f"enriching {checked}/{len(selected_indexes)}: {title} ({item.get('id')})", flush=True)
        prepared, prepared_change = complete_item_metadata(item)
        if args.metadata_only:
            if prepared_change:
                changed += 1
            items[item_index] = prepared
            continue
        attempted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        updated, did_change, error = enrich_item_metadata(
            prepared,
            timeout=args.timeout,
            preserve_existing=True,
        )
        if error:
            failed += 1
            updated = with_enrichment_status(
                prepared,
                attempted_at=attempted_at,
                status="failed",
                missing_fields=missing_reader_fields(prepared),
                error=error,
            )
            changed += 1
            items[item_index] = updated
            print(f"failed {item.get('id')}: {error}")
            continue
        missing_fields = missing_reader_fields(updated)
        updated = with_enrichment_status(
            updated,
            attempted_at=attempted_at,
            status="complete" if not missing_fields else "partial",
            missing_fields=missing_fields,
        )
        changed += 1
        items[item_index] = updated

    if not args.dry_run:
        write_jsonl(args.items, items)
    skipped = max(0, len(candidates) - checked)
    write_status(
        args.status_file,
        {
            "command": "enrich_reader_metadata",
            "state": "done" if failed == 0 else "failed",
            "message": "補閱讀卡圖片、描述與主文完成" if failed == 0 else "補閱讀卡圖片、描述與主文有失敗項目",
            "checked": checked,
            "changed": changed,
            "failed": failed,
            "skipped": skipped,
            "cooldown": cooldown,
            "eligible": len(candidates),
        },
    )
    print(
        f"checked={checked} changed={changed} failed={failed} skipped={skipped} "
        f"cooldown={cooldown} eligible={len(candidates)} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
