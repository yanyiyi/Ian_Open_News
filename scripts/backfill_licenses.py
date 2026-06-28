#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
ITEMS = DATABASE / "items.jsonl"
ARTICLES = DATABASE / "articles.jsonl"
TAXONOMY = DATABASE / "taxonomy.json"

LICENSE_UNSPECIFIED = "未明確標示"
LICENSE_NON_CC_PREFIX = "非 CC："
LICENSE_URLS = {
    "CC BY 4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY-SA 4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-NC 4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC BY-NC-SA 4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "CC BY-ND 4.0": "https://creativecommons.org/licenses/by-nd/4.0/",
    "CC BY-NC-ND 4.0": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "CC BY 3.0 TW": "https://creativecommons.org/licenses/by/3.0/tw/",
    "CC BY-SA 3.0 TW": "https://creativecommons.org/licenses/by-sa/3.0/tw/",
    "CC BY-NC 3.0 TW": "https://creativecommons.org/licenses/by-nc/3.0/tw/",
    "CC BY-NC-SA 3.0 TW": "https://creativecommons.org/licenses/by-nc-sa/3.0/tw/",
    "CC BY-ND 3.0 TW": "https://creativecommons.org/licenses/by-nd/3.0/tw/",
    "CC BY-NC-ND 3.0 TW": "https://creativecommons.org/licenses/by-nc-nd/3.0/tw/",
    "CC0 1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public Domain Mark 1.0": "https://creativecommons.org/publicdomain/mark/1.0/",
}
CC_SLUGS = {
    "by-nc-nd": "CC BY-NC-ND",
    "by-nc-sa": "CC BY-NC-SA",
    "by-nc": "CC BY-NC",
    "by-nd": "CC BY-ND",
    "by-sa": "CC BY-SA",
    "by": "CC BY",
}
PHRASE_PATTERNS = [
    (re.compile(r"\battribution[\s-]+noncommercial[\s-]+noderivatives\b", re.I), "CC BY-NC-ND"),
    (re.compile(r"\battribution[\s-]+noncommercial[\s-]+sharealike\b", re.I), "CC BY-NC-SA"),
    (re.compile(r"\battribution[\s-]+noncommercial\b", re.I), "CC BY-NC"),
    (re.compile(r"\battribution[\s-]+noderivatives\b", re.I), "CC BY-ND"),
    (re.compile(r"\battribution[\s-]+sharealike\b", re.I), "CC BY-SA"),
    (re.compile(r"\b(?:cc|creative commons)[\s-]+by[\s-]+nc[\s-]+nd\b", re.I), "CC BY-NC-ND"),
    (re.compile(r"\b(?:cc|creative commons)[\s-]+by[\s-]+nc[\s-]+sa\b", re.I), "CC BY-NC-SA"),
    (re.compile(r"\b(?:cc|creative commons)[\s-]+by[\s-]+nc\b", re.I), "CC BY-NC"),
    (re.compile(r"\b(?:cc|creative commons)[\s-]+by[\s-]+nd\b", re.I), "CC BY-ND"),
    (re.compile(r"\b(?:cc|creative commons)[\s-]+by[\s-]+sa\b", re.I), "CC BY-SA"),
    (re.compile(r"\b(?:cc|creative commons)[\s-]+by\b", re.I), "CC BY"),
    (re.compile(r"\battribution\b", re.I), "CC BY"),
]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def clean_text(value: object, limit: int | None = None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def known_license_names() -> set[str]:
    taxonomy = load_json(TAXONOMY)
    return set(taxonomy.get("licenses") or [])


def existing_license_name(record: dict[str, Any]) -> str:
    license_record = record.get("license") if isinstance(record.get("license"), dict) else {}
    return clean_text(license_record.get("name"), 120)


def existing_license_method(record: dict[str, Any]) -> str:
    license_record = record.get("license") if isinstance(record.get("license"), dict) else {}
    provenance = license_record.get("provenance") if isinstance(license_record.get("provenance"), dict) else {}
    return clean_text(provenance.get("method"), 80)


def license_from_url(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    lowered = text.lower()
    if "creativecommons.org/publicdomain/zero/1.0" in lowered:
        return "CC0 1.0", LICENSE_URLS["CC0 1.0"]
    if "creativecommons.org/publicdomain/mark/1.0" in lowered:
        return "Public Domain Mark 1.0", LICENSE_URLS["Public Domain Mark 1.0"]
    match = re.search(r"creativecommons\.org/licenses/(by-nc-nd|by-nc-sa|by-nc|by-nd|by-sa|by)/(4\.0|3\.0)(?:/(tw))?", lowered)
    if not match:
        return "", ""
    slug, version, tw = match.groups()
    base = CC_SLUGS.get(slug, "")
    if version == "4.0" and base:
        name = f"{base} 4.0"
        return name, LICENSE_URLS.get(name, "")
    if version == "3.0" and tw and base:
        name = f"{base} 3.0 TW"
        return name, LICENSE_URLS.get(name, "")
    return "", ""


def normalized_phrase_text(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"(?i)cc[-_ ]?by", "CC BY", text)
    text = re.sub(r"[-_/]+", " ", text)
    return text


def version_suffix(text: str) -> str:
    lowered = text.lower()
    if re.search(r"\b4\.0\b", lowered) or "4.0 international" in lowered:
        return "4.0"
    if re.search(r"\b3\.0\b", lowered) and re.search(r"\b(tw|taiwan)\b|臺灣|台灣", lowered):
        return "3.0 TW"
    return ""


def license_from_phrase(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    if re.search(r"\bcc0\b|public domain dedication|zero 1\.0", lowered):
        return "CC0 1.0"
    if "public domain mark" in lowered:
        return "Public Domain Mark 1.0"
    normalized = normalized_phrase_text(text)
    suffix = version_suffix(normalized)
    if not suffix:
        return ""
    for pattern, base in PHRASE_PATTERNS:
        if pattern.search(normalized):
            name = f"{base} {suffix}"
            return name if name in LICENSE_URLS else ""
    return ""


def explicit_non_cc(text: str) -> str:
    lowered = text.lower()
    if "未標示" in text or "未明確" in text or "推定" in text or "推斷" in text:
        return ""
    if "all rights reserved" in lowered or "著作權所有" in text or "版權所有" in text:
        return f"{LICENSE_NON_CC_PREFIX}著作權保護"
    return ""


def body_has_license_context(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in [
            "released under",
            "licensed under",
            "is licensed",
            "creative commons",
            "creativecommons.org",
            "授權",
            "本頁",
            "本作品",
        ]
    )


def evidence_candidates(record: dict[str, Any], kind: str) -> list[tuple[str, str, str]]:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    reference = record.get("reference") if isinstance(record.get("reference"), dict) else {}
    raw_columns = reference.get("raw_columns") if isinstance(reference.get("raw_columns"), dict) else {}
    candidates: list[tuple[str, str, str]] = []
    if kind == "item":
        original_license = clean_text(metadata.get("original_license"))
        original_license_url = clean_text(metadata.get("original_license_url"))
        if original_license or original_license_url:
            candidates.append(("reading_metadata.original_license", "\n".join([original_license, original_license_url]), "high"))
        notes = clean_text(raw_columns.get("備註"))
        if notes:
            candidates.append(('reference.raw_columns["備註"]', notes, "medium"))
        cached = "\n".join(
            clean_text(value)
            for value in [
                metadata.get("canonical_url"),
                metadata.get("source_url"),
                metadata.get("article_markdown"),
                metadata.get("article_text"),
            ]
            if clean_text(value)
        )
        if cached:
            candidates.append(("reading_metadata.article", cached, "body"))
    article_text = "\n".join(
        clean_text(value)
        for value in [
            record.get("body_markdown"),
            record.get("summary"),
            record.get("title"),
            record.get("url"),
        ]
        if clean_text(value)
    )
    if article_text:
        candidates.append(("summary/title/url", article_text, "body"))
    return candidates


def infer_license(record: dict[str, Any], kind: str) -> tuple[str, str, str, str]:
    for source_field, text, confidence_hint in evidence_candidates(record, kind):
        name, url = license_from_url(text)
        if not name:
            name = license_from_phrase(text)
            url = LICENSE_URLS.get(name, "") if name else ""
        if name:
            if confidence_hint == "body" and not body_has_license_context(text):
                return LICENSE_UNSPECIFIED, "", "low", source_field
            return name, url, "high" if confidence_hint != "body" else "medium", source_field
        non_cc = explicit_non_cc(text)
        if non_cc:
            return non_cc, "", "medium", source_field
        if re.search(r"creative commons|creativecommons|創用\s*cc|cc\s*授權", text, re.I):
            return LICENSE_UNSPECIFIED, "", "low", source_field
    return LICENSE_UNSPECIFIED, "", "low", "default"


def evidence_for(record: dict[str, Any], license_url: str) -> dict[str, str]:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    evidence = {
        "source_url": clean_text(metadata.get("source_url") or metadata.get("canonical_url") or record.get("url"), 1000),
        "page_title": clean_text(metadata.get("original_site_title") or metadata.get("title") or record.get("title"), 500),
        "rights_holder": clean_text(metadata.get("original_author") or record.get("author") or record.get("source_name"), 500),
        "license_link_url": clean_text(license_url or metadata.get("original_license_url"), 1000),
        "access_date": today(),
    }
    return {key: value for key, value in evidence.items() if value}


def attribution_for(record: dict[str, Any], name: str) -> list[dict[str, str]]:
    if not name or name == LICENSE_UNSPECIFIED:
        return []
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    attribution = clean_text(metadata.get("original_author") or record.get("author") or record.get("source_name") or metadata.get("site_name"), 500)
    if not attribution:
        attribution = clean_text(metadata.get("original_site_title") or record.get("title"), 500) or "未明確標示"
    return [{"scope": "整頁", "attribution": attribution, "license_name": name}]


def build_license(record: dict[str, Any], kind: str, method: str = "backfill-heuristic") -> dict[str, Any]:
    name, license_url, confidence, source_field = infer_license(record, kind)
    license_record: dict[str, Any] = {
        "name": name,
        "uncertain": name == LICENSE_UNSPECIFIED or confidence == "low",
        "evidence": evidence_for(record, license_url),
        "provenance": {
            "method": method,
            "determined_at": now_iso(),
            "confidence": confidence,
            "source_field": source_field,
        },
    }
    if license_url:
        license_record["license_url"] = license_url
    table = attribution_for(record, name)
    if table:
        license_record["attribution_table"] = table
    return license_record


def should_skip(record: dict[str, Any], args: argparse.Namespace) -> bool:
    record_id = clean_text(record.get("id"))
    if args.id and record_id not in args.id:
        return True
    if existing_license_method(record) == "manual":
        return True
    if args.only_missing and existing_license_name(record):
        return True
    return False


def process_file(path: Path, kind: str, args: argparse.Namespace) -> tuple[int, Counter[str]]:
    records = load_jsonl(path)
    changed = 0
    stats: Counter[str] = Counter()
    updated_records = []
    known_names = known_license_names()
    for record in records:
        if should_skip(record, args):
            updated_records.append(record)
            continue
        license_record = build_license(record, kind)
        name = clean_text(license_record.get("name"))
        if name not in known_names and not name.startswith(LICENSE_NON_CC_PREFIX):
            license_record["name"] = LICENSE_UNSPECIFIED
            license_record["uncertain"] = True
            license_record.pop("license_url", None)
        stats[license_record["name"]] += 1
        if record.get("license") != license_record:
            changed += 1
            record = {**record, "license": license_record}
        updated_records.append(record)
    if changed and not args.dry_run:
        write_jsonl(path, updated_records)
    return changed, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill normalized license objects for Ian Open News items/articles.")
    parser.add_argument("--items", action="store_true", help="Process database/items.jsonl.")
    parser.add_argument("--articles", action="store_true", help="Process database/articles.jsonl.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-missing", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fetch", action=argparse.BooleanOptionalAction, default=False, help="Reserved for per-record online refresh; offline by default.")
    parser.add_argument("--llm", action=argparse.BooleanOptionalAction, default=False, help="Reserved for ambiguous evidence review; disabled unless implemented.")
    parser.add_argument("--id", action="append", default=[], help="Only process a specific item/article id. Can be repeated.")
    args = parser.parse_args()

    selected = []
    if args.items:
        selected.append((ITEMS, "item"))
    if args.articles:
        selected.append((ARTICLES, "article"))
    if not selected:
        selected = [(ITEMS, "item"), (ARTICLES, "article")]

    if args.fetch:
        print("note: --fetch is accepted but this pass remains offline; cached evidence only.")
    if args.llm:
        print("note: --llm is accepted but no LLM call is made in this offline implementation.")

    total_changed = 0
    total_stats: Counter[str] = Counter()
    for path, kind in selected:
        changed, stats = process_file(path, kind, args)
        total_changed += changed
        total_stats.update(stats)
        print(f"{path.relative_to(ROOT)}: would_update={changed}" if args.dry_run else f"{path.relative_to(ROOT)}: updated={changed}")
        for name, count in stats.most_common():
            print(f"  {name}: {count}")
    mode = "dry-run" if args.dry_run else "write"
    print(f"license backfill complete mode={mode} changed={total_changed}")
    if total_stats:
        print("total:")
        for name, count in total_stats.most_common():
            print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
