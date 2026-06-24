#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    if not path.exists():
        return records
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        record["_line"] = line_number
        records.append(record)
    return records


def require(record: dict, path: Path, field: str) -> str:
    value = record.get(field)
    if value in (None, ""):
        raise ValueError(f"{path}:{record.get('_line', '?')}: missing required field {field}")
    return str(value)


def validate_unique(records: list[dict], path: Path) -> None:
    seen: dict[str, int] = {}
    for record in records:
        record_id = require(record, path, "id")
        if record_id in seen:
            raise ValueError(f"{path}:{record['_line']}: duplicate id {record_id}; first seen on line {seen[record_id]}")
        seen[record_id] = record["_line"]


def validate() -> list[str]:
    taxonomy = load_json(DATABASE / "taxonomy.json")
    tracks = set(taxonomy["tracks"].keys())
    statuses = set(taxonomy["statuses"])
    priorities = set(taxonomy["priorities"])
    source_types = set(taxonomy["source_types"])
    source_statuses = set(taxonomy.get("source_statuses", ["active", "paused", "archived"]))
    review_steps = set(taxonomy["review_steps"])

    article_statuses = {"draft", "ready", "published"}

    sources_path = DATABASE / "sources.jsonl"
    items_path = DATABASE / "items.jsonl"
    rejected_items_path = DATABASE / "rejected-items.jsonl"
    reviews_path = DATABASE / "review-events.jsonl"
    articles_path = DATABASE / "articles.jsonl"
    sources = load_jsonl(sources_path)
    items = load_jsonl(items_path)
    rejected_items = load_jsonl(rejected_items_path)
    reviews = load_jsonl(reviews_path)
    articles = load_jsonl(articles_path)

    validate_unique(sources, sources_path)
    validate_unique(items, items_path)
    validate_unique(rejected_items, rejected_items_path)
    validate_unique(reviews, reviews_path)
    validate_unique(articles, articles_path)

    errors: list[str] = []
    source_ids = {record["id"] for record in sources}
    item_ids = {record["id"] for record in items}
    rejected_item_ids = {record["id"] for record in rejected_items}
    duplicated_archives = item_ids & rejected_item_ids
    for item_id in sorted(duplicated_archives):
        errors.append(f"{rejected_items_path}: duplicate active/rejected item id {item_id}")

    for source in sources:
        try:
            require(source, sources_path, "name")
            require(source, sources_path, "track")
            require(source, sources_path, "source_type")
            require(source, sources_path, "status")
            if source["track"] not in tracks:
                errors.append(f"{sources_path}:{source['_line']}: unknown track {source['track']}")
            if source["source_type"] not in source_types:
                errors.append(f"{sources_path}:{source['_line']}: unknown source_type {source['source_type']}")
            if source["status"] not in source_statuses:
                errors.append(f"{sources_path}:{source['_line']}: unknown source status {source['status']}")
        except ValueError as exc:
            errors.append(str(exc))

    for item in items:
        try:
            require(item, items_path, "track")
            require(item, items_path, "status")
            require(item, items_path, "priority")
            require(item, items_path, "title")
            require(item, items_path, "source_id")
            require(item, items_path, "source_name")
            require(item, items_path, "origin")
            if item["track"] not in tracks:
                errors.append(f"{items_path}:{item['_line']}: unknown track {item['track']}")
            if item["status"] not in statuses:
                errors.append(f"{items_path}:{item['_line']}: unknown status {item['status']}")
            if item["priority"] not in priorities:
                errors.append(f"{items_path}:{item['_line']}: unknown priority {item['priority']}")
            if item["source_id"] not in source_ids:
                errors.append(f"{items_path}:{item['_line']}: source_id not found: {item['source_id']}")
            if not isinstance(item.get("tags"), list):
                errors.append(f"{items_path}:{item['_line']}: tags must be a list")
            if not isinstance(item.get("reference"), dict):
                errors.append(f"{items_path}:{item['_line']}: reference must be an object")
            if not isinstance(item.get("review"), dict):
                errors.append(f"{items_path}:{item['_line']}: review must be an object")
            if "reader_flags" in item and not isinstance(item.get("reader_flags"), dict):
                errors.append(f"{items_path}:{item['_line']}: reader_flags must be an object")
            if "tag_metadata" in item and not isinstance(item.get("tag_metadata"), dict):
                errors.append(f"{items_path}:{item['_line']}: tag_metadata must be an object")
        except ValueError as exc:
            errors.append(str(exc))

    for item in rejected_items:
        try:
            require(item, rejected_items_path, "track")
            require(item, rejected_items_path, "status")
            require(item, rejected_items_path, "priority")
            require(item, rejected_items_path, "title")
            require(item, rejected_items_path, "source_id")
            require(item, rejected_items_path, "source_name")
            require(item, rejected_items_path, "origin")
            if item["track"] not in tracks:
                errors.append(f"{rejected_items_path}:{item['_line']}: unknown track {item['track']}")
            if item["status"] not in statuses:
                errors.append(f"{rejected_items_path}:{item['_line']}: unknown status {item['status']}")
            if item["priority"] not in priorities:
                errors.append(f"{rejected_items_path}:{item['_line']}: unknown priority {item['priority']}")
            if item["source_id"] not in source_ids:
                errors.append(f"{rejected_items_path}:{item['_line']}: source_id not found: {item['source_id']}")
            if not isinstance(item.get("tags"), list):
                errors.append(f"{rejected_items_path}:{item['_line']}: tags must be a list")
            if not isinstance(item.get("reference"), dict):
                errors.append(f"{rejected_items_path}:{item['_line']}: reference must be an object")
            if not isinstance(item.get("review"), dict):
                errors.append(f"{rejected_items_path}:{item['_line']}: review must be an object")
            if "reader_flags" in item and not isinstance(item.get("reader_flags"), dict):
                errors.append(f"{rejected_items_path}:{item['_line']}: reader_flags must be an object")
            if "tag_metadata" in item and not isinstance(item.get("tag_metadata"), dict):
                errors.append(f"{rejected_items_path}:{item['_line']}: tag_metadata must be an object")
            decision = item.get("local_decision")
            if not isinstance(decision, dict) or decision.get("action") != "rejected":
                errors.append(f"{rejected_items_path}:{item['_line']}: local_decision.action must be rejected")
        except ValueError as exc:
            errors.append(str(exc))

    for review in reviews:
        try:
            item_id = require(review, reviews_path, "item_id")
            require(review, reviews_path, "track")
            require(review, reviews_path, "step")
            require(review, reviews_path, "status")
            if item_id != "manual-seed" and item_id not in item_ids and item_id not in rejected_item_ids:
                errors.append(f"{reviews_path}:{review['_line']}: item_id not found: {item_id}")
            if review["track"] not in tracks:
                errors.append(f"{reviews_path}:{review['_line']}: unknown track {review['track']}")
            if review["step"] not in review_steps:
                errors.append(f"{reviews_path}:{review['_line']}: unknown review step {review['step']}")
            if not isinstance(review.get("evidence"), list):
                errors.append(f"{reviews_path}:{review['_line']}: evidence must be a list")
        except ValueError as exc:
            errors.append(str(exc))

    for article in articles:
        try:
            require(article, articles_path, "title")
            require(article, articles_path, "track")
            require(article, articles_path, "status")
            if article["track"] not in tracks:
                errors.append(f"{articles_path}:{article['_line']}: unknown track {article['track']}")
            if article["status"] not in article_statuses:
                errors.append(f"{articles_path}:{article['_line']}: unknown article status {article['status']}")
            if not isinstance(article.get("tags"), list):
                errors.append(f"{articles_path}:{article['_line']}: tags must be a list")
            # item_ids / viewpoint_ids 可能指向候選池或已刪觀點，這裡只檢型別、不強制外鍵存在。
            if not isinstance(article.get("item_ids"), list):
                errors.append(f"{articles_path}:{article['_line']}: item_ids must be a list")
            if not isinstance(article.get("viewpoint_ids"), list):
                errors.append(f"{articles_path}:{article['_line']}: viewpoint_ids must be a list")
            if "factcheck" in article and not isinstance(article.get("factcheck"), dict):
                errors.append(f"{articles_path}:{article['_line']}: factcheck must be an object")
            factcheck = article.get("factcheck")
            if isinstance(factcheck, dict) and "claims" in factcheck and not isinstance(factcheck.get("claims"), list):
                errors.append(f"{articles_path}:{article['_line']}: factcheck.claims must be a list")
        except ValueError as exc:
            errors.append(str(exc))

    return errors


def main() -> None:
    errors = validate()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        raise SystemExit(1)
    print("database validation passed")


if __name__ == "__main__":
    main()
