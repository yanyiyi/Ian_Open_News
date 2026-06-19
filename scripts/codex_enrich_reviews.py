#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
REPORT = ROOT / ".cache" / "codex-review-report.md"

READER_STATUSES = {"triaged", "researching", "drafting", "reviewing", "fact-checking", "ready", "published"}
READER_ACTIONS = {"accepted-for-editing", "direct-pr-small-news", "revisit-with-personal-notes"}


def clean_text(value: object, limit: int | None = None) -> str:
    if value is None:
        return ""
    text = str(value)
    text = " ".join(text.replace("\r", "\n").split()) if "\n" not in text else text
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    text = "\n".join(line for line in text.split("\n") if line).strip()
    if limit and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not line.strip():
            continue
        record = json.loads(line)
        record["_line"] = line_number
        records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def codex_path() -> str:
    candidate = shutil.which("codex")
    if candidate:
        return candidate
    for path in ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"]:
        if Path(path).exists():
            return path
    raise RuntimeError("找不到 codex CLI，請先確認 /opt/homebrew/bin/codex 是否可用。")


def has_codex_review(record: dict[str, Any]) -> bool:
    editorial = record.get("editorial_triage")
    if not isinstance(editorial, dict):
        return False
    return isinstance(editorial.get("codex_review"), dict)


def local_decision_action(record: dict[str, Any]) -> str:
    decision = record.get("local_decision")
    if not isinstance(decision, dict):
        return ""
    return str(decision.get("action") or "")


def in_item_scope(record: dict[str, Any], tracks: set[str], statuses: set[str], workflow_scope: bool) -> bool:
    if tracks and record.get("track") not in tracks:
        return False
    if workflow_scope:
        status = record.get("status")
        action = local_decision_action(record)
        return status == "inbox" or status in READER_STATUSES or action in READER_ACTIONS
    return record.get("status") in statuses


def in_candidate_scope(record: dict[str, Any], tracks: set[str]) -> bool:
    if tracks and record.get("track") not in tracks:
        return False
    return record.get("candidate_status", "pending") == "pending"


def source_material(record: dict[str, Any]) -> tuple[str, str, bool]:
    reading = record.get("reading_metadata")
    reading = reading if isinstance(reading, dict) else {}
    enrichment = record.get("article_enrichment")
    enrichment = enrichment if isinstance(enrichment, dict) else {}

    article_text = clean_text(reading.get("article_text"), 5000)
    if article_text:
        return article_text, "主文全文", False

    sentences = enrichment.get("summary_sentences")
    if isinstance(sentences, list):
        text = clean_text("\n".join(str(sentence) for sentence in sentences if sentence), 2200)
        if text:
            return text, "已抽取正文摘要", True

    summary = clean_text(record.get("summary"), 2200)
    description = clean_text(reading.get("description"), 1200)
    if summary and description and description not in summary:
        return f"{summary}\n{description}", "RSS 摘要與頁面描述", True
    if summary:
        return summary, "RSS 摘要", True
    if description:
        return description, "頁面描述", True

    title = clean_text(record.get("title"), 500)
    return title, "只有標題", True


def review_input(record: dict[str, Any]) -> dict[str, Any]:
    text, basis, needs_fulltext = source_material(record)
    triage = record.get("triage") if isinstance(record.get("triage"), dict) else {}
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    return {
        "id": record.get("id"),
        "track": record.get("track"),
        "status": record.get("status"),
        "title": clean_text(record.get("title"), 360),
        "url": record.get("url", ""),
        "source_name": record.get("source_name", ""),
        "published_at": record.get("published_at", ""),
        "tags": record.get("tags", [])[:12] if isinstance(record.get("tags"), list) else [],
        "local_rule_recommendation": triage.get("recommendation", ""),
        "matched_keywords": triage.get("matched_keywords", []),
        "local_content_kind": editorial.get("content_kind", ""),
        "source_basis": basis,
        "needs_fulltext": needs_fulltext,
        "source_text": text,
    }


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reviews"],
        "properties": {
            "reviews": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "zh_title",
                        "one_line_recommendation",
                        "reasons",
                        "summary",
                        "recommendation",
                        "content_kind",
                        "confidence",
                        "needs_fulltext",
                        "note",
                    ],
                    "properties": {
                        "id": {"type": "string"},
                        "zh_title": {"type": "string"},
                        "one_line_recommendation": {"type": "string"},
                        "reasons": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": {"type": "string"},
                        },
                        "summary": {"type": "string"},
                        "recommendation": {
                            "type": "string",
                            "enum": ["recommend-collect", "recommend-review", "recommend-skip"],
                        },
                        "content_kind": {
                            "type": "string",
                            "enum": ["featured-article", "small-news", "needs-review"],
                        },
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "needs_fulltext": {"type": "boolean"},
                        "note": {"type": "string"},
                    },
                },
            }
        },
    }


def build_prompt(batch: list[dict[str, Any]]) -> str:
    data = json.dumps({"items": batch}, ensure_ascii=False, indent=2)
    return f"""你是 Ian Open News 的編輯助理，請為下列 RSS/知識項目補上 Codex 版閱讀建議。

請只根據每筆提供的 source_text 判斷，不要上網，不要補不存在的事實。
若 source_basis 是「只有標題」或 source_text 太短，請明確降低 confidence，needs_fulltext 設為 true，摘要只做保守判斷。

每筆請產生：
- zh_title：如果原標題是英文，翻成自然繁體中文；如果已是中文，可微調成清楚標題。
- one_line_recommendation：用「給 Ian 的一句話推薦」語氣，說清楚值不值得先看，以及最有價值的角度。
- reasons：三個「看它的理由」，要是編輯判斷，不要只是重複關鍵字。
- summary：繁體中文摘要，盡量像人讀完後重寫，避免「這是一篇英文資料，可能和...有關」這種模板句。
- recommendation：recommend-collect / recommend-review / recommend-skip。
- content_kind：featured-article 表示值得跑 skill；small-news 表示純新聞或小消息可直接查核送 PR；needs-review 表示需要人工判斷。
- note：一句話說明判斷依據或限制。

回覆必須符合 JSON schema，不要輸出 Markdown。

資料：
{data}
"""


def run_codex(batch: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema_path = cache / "codex-review.schema.json"
    output_path = cache / "codex-review-output.json"
    prompt_path = cache / "codex-review-prompt.json"
    schema_path.write_text(json.dumps(output_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
    prompt = build_prompt(batch)
    prompt_path.write_text(prompt, encoding="utf-8")

    command = [
        codex_path(),
        "-a",
        "never",
        "exec",
        "--ephemeral",
        "--cd",
        str(ROOT),
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "-",
    ]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command,
        cwd=ROOT,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "codex exec failed\n"
            f"STDOUT:\n{result.stdout[-2000:]}\n"
            f"STDERR:\n{result.stderr[-2000:]}"
        )
    raw = output_path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        raise RuntimeError("Codex output missing reviews array")
    return reviews


def formatted_summary(review: dict[str, Any]) -> str:
    reasons = review.get("reasons") if isinstance(review.get("reasons"), list) else []
    reasons = [clean_text(reason) for reason in reasons[:3]]
    while len(reasons) < 3:
        reasons.append("來源資訊不足，建議補抓全文後再判斷。")
    return "\n".join(
        [
            f"中文標題：{clean_text(review.get('zh_title'))}",
            "",
            f"給 Ian 的一句話推薦：{clean_text(review.get('one_line_recommendation'))}",
            "",
            "三個看它的理由",
            f"1. {reasons[0]}",
            f"2. {reasons[1]}",
            f"3. {reasons[2]}",
            "",
            "摘要",
            clean_text(review.get("summary")),
        ]
    ).strip()


def apply_reviews(records: list[dict[str, Any]], reviews: list[dict[str, Any]]) -> int:
    by_id = {str(review.get("id")): review for review in reviews if review.get("id")}
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = 0
    for record in records:
        record_id = str(record.get("id") or "")
        review = by_id.get(record_id)
        if not review:
            continue
        editorial = record.get("editorial_triage")
        if not isinstance(editorial, dict):
            editorial = {}
        reasons = review.get("reasons") if isinstance(review.get("reasons"), list) else []
        reasons = [clean_text(reason) for reason in reasons[:3]]
        while len(reasons) < 3:
            reasons.append("來源資訊不足，建議補抓全文後再判斷。")
        codex_review = {
            "source": "Codex",
            "generator": "codex-cli",
            "generated_at": generated_at,
            "version": 1,
            "zh_title": clean_text(review.get("zh_title"), 300),
            "one_line_recommendation": clean_text(review.get("one_line_recommendation"), 500),
            "reasons": reasons,
            "summary": clean_text(review.get("summary"), 1600),
            "recommendation": review.get("recommendation"),
            "content_kind": review.get("content_kind"),
            "confidence": review.get("confidence"),
            "needs_fulltext": bool(review.get("needs_fulltext")),
            "note": clean_text(review.get("note"), 500),
        }
        editorial["codex_review"] = codex_review
        editorial["zh_title"] = codex_review["zh_title"] or clean_text(record.get("title"), 300)
        editorial["zh_summary"] = formatted_summary(review)
        editorial["summary_reason"] = "已由 Codex 依目前可讀資料補閱讀建議與摘要。"
        editorial["codex_generated_at"] = generated_at
        record["editorial_triage"] = editorial
        changed += 1
    return changed


def batched(records: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [records[index : index + size] for index in range(0, len(records), size)]


def collect_targets(records: list[dict[str, Any]], args: argparse.Namespace, kind: str) -> list[dict[str, Any]]:
    tracks = set(args.track or [])
    statuses = set(args.status or [])
    selected: list[dict[str, Any]] = []
    for record in records:
        if args.missing_only and has_codex_review(record):
            continue
        if kind == "items":
            if not in_item_scope(record, tracks, statuses, args.workflow_scope):
                continue
        else:
            if not in_candidate_scope(record, tracks):
                continue
        selected.append(record)
    return selected[: args.limit] if args.limit else selected


def process_file(path: Path, kind: str, args: argparse.Namespace) -> tuple[int, int]:
    records = load_jsonl(path)
    targets = collect_targets(records, args, kind)
    if args.prepare_only or not targets:
        return len(targets), 0

    changed = 0
    for batch_records in batched(targets, max(1, args.batch_size)):
        batch_input = [review_input(record) for record in batch_records]
        reviews = run_codex(batch_input, args)
        batch_changed = apply_reviews(records, reviews)
        changed += batch_changed
        if batch_changed and not args.dry_run:
            for record in records:
                record.pop("_line", None)
            write_jsonl(path, records)
        print(f"{kind}: batch selected {len(batch_records)}, updated {batch_changed}", flush=True)
    return len(targets), changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Use Codex CLI to add reading recommendations and summaries.")
    parser.add_argument("--target", choices=["candidates", "items", "both"], default="candidates")
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--track", action="append", default=[])
    parser.add_argument("--status", action="append", default=["inbox"])
    parser.add_argument("--workflow-scope", action="store_true", help="For items, include inbox plus reader/workflow statuses.")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--missing-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prepare-only", action="store_true", help="Only count records that would be sent to Codex.")
    parser.add_argument("--dry-run", action="store_true", help="Call Codex but do not write JSONL.")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()

    totals: list[tuple[str, int, int]] = []
    if args.target in {"candidates", "both"}:
        totals.append(("RSS 暫存", *process_file(args.candidates, "candidates", args)))
    if args.target in {"items", "both"}:
        totals.append(("資料庫項目", *process_file(args.items, "items", args)))

    lines = [
        "# Codex review enrichment report",
        "",
        f"- Generated at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Target: {args.target}",
        f"- Tracks: {', '.join(args.track) if args.track else 'all'}",
        f"- Mode: {'prepare only' if args.prepare_only else 'dry run' if args.dry_run else 'write'}",
        "",
    ]
    for label, selected, changed in totals:
        lines.append(f"- {label}: selected {selected}, updated {changed}")
    text = "\n".join(lines).rstrip() + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
