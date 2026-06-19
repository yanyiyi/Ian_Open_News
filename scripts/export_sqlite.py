#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Export database/*.jsonl to a local SQLite database")
    parser.add_argument("--output", type=Path, default=ROOT / ".cache" / "knowledge.sqlite")
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        args.output.unlink()

    connection = sqlite3.connect(args.output)
    try:
        connection.executescript((DATABASE / "schema.sql").read_text(encoding="utf-8"))
        for source in load_jsonl(DATABASE / "sources.jsonl"):
            connection.execute(
                """
                INSERT INTO sources
                (id, track, name, source_group, source_type, feed_url, site_url, status, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source["id"],
                    source["track"],
                    source["name"],
                    source.get("source_group", ""),
                    source["source_type"],
                    source.get("feed_url", ""),
                    source.get("site_url", ""),
                    source["status"],
                    source.get("notes", ""),
                ),
            )
        for item in load_jsonl(DATABASE / "items.jsonl"):
            connection.execute(
                """
                INSERT INTO items
                (id, track, status, priority, title, url, source_id, source_name, author,
                 published_at, captured_at, summary, tags_json, origin, reference_json, review_json,
                 editorial_triage_json, personal_notes_json, reading_metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["track"],
                    item["status"],
                    item["priority"],
                    item["title"],
                    item.get("url", ""),
                    item["source_id"],
                    item["source_name"],
                    item.get("author", ""),
                    item.get("published_at", ""),
                    item.get("captured_at", ""),
                    item.get("summary", ""),
                    json.dumps(item.get("tags", []), ensure_ascii=False),
                    item["origin"],
                    json.dumps(item.get("reference", {}), ensure_ascii=False),
                    json.dumps(item.get("review", {}), ensure_ascii=False),
                    json.dumps(item.get("editorial_triage", {}), ensure_ascii=False),
                    json.dumps(item.get("personal_notes", {}), ensure_ascii=False),
                    json.dumps(item.get("reading_metadata", {}), ensure_ascii=False),
                ),
            )
        for review in load_jsonl(DATABASE / "review-events.jsonl"):
            if review.get("item_id") == "manual-seed":
                continue
            connection.execute(
                """
                INSERT INTO review_events
                (id, item_id, track, step, status, reviewer, created_at, notes, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review["id"],
                    review["item_id"],
                    review["track"],
                    review["step"],
                    review["status"],
                    review.get("reviewer", ""),
                    review.get("created_at", ""),
                    review.get("notes", ""),
                    json.dumps(review.get("evidence", []), ensure_ascii=False),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
