#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"


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
            print(f"warning: skip invalid JSONL {path}:{line_number}: {exc}", file=sys.stderr)
    return records


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
                (id, track, name, source_group, source_type, fetch_frequency, feed_url, site_url, status,
                 required_keywords_json, excluded_keywords_json, rss_health_json, health_assessment_json, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source["id"],
                    source["track"],
                    source["name"],
                    source.get("source_group", ""),
                    source["source_type"],
                    source.get("fetch_frequency", "daily"),
                    source.get("feed_url", ""),
                    source.get("site_url", ""),
                    source["status"],
                    json.dumps(source.get("required_keywords", []), ensure_ascii=False),
                    json.dumps(source.get("excluded_keywords", []), ensure_ascii=False),
                    json.dumps(source.get("rss_health", {}), ensure_ascii=False),
                    json.dumps(source.get("health_assessment", {}), ensure_ascii=False),
                    source.get("notes", ""),
                ),
            )
        active_item_ids: set[str] = set()
        for item in load_jsonl(DATABASE / "items.jsonl"):
            active_item_ids.add(item["id"])
            connection.execute(
                """
                INSERT INTO items
                (id, track, status, priority, title, url, source_id, source_name, author,
                 published_at, captured_at, summary, tags_json, origin, reference_json, review_json,
                 editorial_triage_json, personal_notes_json, reader_flags_json, reading_metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(item.get("reader_flags", {}), ensure_ascii=False),
                    json.dumps(item.get("reading_metadata", {}), ensure_ascii=False),
                ),
            )
        for review in load_jsonl(DATABASE / "review-events.jsonl"):
            if review.get("item_id") == "manual-seed":
                continue
            if review.get("item_id") not in active_item_ids:
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
        for article in load_jsonl(DATABASE / "articles.jsonl"):
            connection.execute(
                """
                INSERT INTO articles
                (id, title, slug, track, status, body_markdown, tags_json, item_ids_json,
                 viewpoint_ids_json, source_session_id, factcheck_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article["id"],
                    article.get("title", ""),
                    article.get("slug", ""),
                    article["track"],
                    article["status"],
                    article.get("body_markdown", ""),
                    json.dumps(article.get("tags", []), ensure_ascii=False),
                    json.dumps(article.get("item_ids", []), ensure_ascii=False),
                    json.dumps(article.get("viewpoint_ids", []), ensure_ascii=False),
                    article.get("source_session_id", ""),
                    json.dumps(article.get("factcheck", {}), ensure_ascii=False),
                    article.get("created_at", ""),
                    article.get("updated_at", ""),
                ),
            )
        connection.commit()
    finally:
        connection.close()
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
