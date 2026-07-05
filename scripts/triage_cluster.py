#!/usr/bin/env python3
"""跨篇分群分流：把 pending 候選依主題分群，給收/略過/併稿建議與三層閱讀深度。

與 codex_enrich_reviews.py 的分工：
- enrich 是「逐筆獨立判斷」（單篇閱讀建議）；
- 本 script 是「跨篇一次性判斷」——哪些文章會被抓在一起、值得投資多深。

歷史 ground truth：database/articles.jsonl 的 item_ids（過去真的被抓在一起
成文的組合）+ .cache/editor-sessions.jsonl 的 compose session + material-links。

輸出兩層：
1. 整批 → .cache/triage-clusters.json（最新 run）+ .cache/triage-cluster-runs.jsonl（審計）
2. 逐筆 → record.editorial_triage.cluster（寫回 rss-candidates.jsonl / items.jsonl）

決策權在 Ian：本 script 只分堆與預選，不改 candidate_status / status。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codex_enrich_reviews import (
    CANDIDATES,
    ITEMS,
    ROOT,
    claude_path,
    clean_text,
    codex_path,
    load_jsonl,
    parse_cli_json,
    review_input,
    taste_profile_block,
    write_jsonl,
    write_status,
)

ARTICLES = ROOT / "database" / "articles.jsonl"
MATERIAL_LINKS = ROOT / "database" / "material-links.jsonl"
REJECTED_ITEMS = ROOT / "database" / "rejected-items.jsonl"
EDITOR_SESSIONS = ROOT / ".cache" / "editor-sessions.jsonl"
CLUSTERS_LATEST = ROOT / ".cache" / "triage-clusters.json"
CLUSTERS_RUNS = ROOT / ".cache" / "triage-cluster-runs.jsonl"
CLUSTERS_PREVIEW = ROOT / ".cache" / "triage-clusters-preview.json"

READING_DEPTHS = ["news-brief", "knowledge-worthy", "deep-read"]
SUGGESTED_ACTIONS = ["collect-as-theme", "collect-individual", "merge-into-item", "skip", "ask"]
ANCHOR_STATUSES = {"researching", "drafting"}
# ollama 的 4B/12B 模型塞不下上百筆跨篇比較，不開放。
CLUSTER_ENGINES = ["claude", "codex"]


def cluster_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["clusters", "ungrouped_ids"],
        "properties": {
            "clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "cluster_id",
                        "label",
                        "angle_hint",
                        "member_ids",
                        "suggested_action",
                        "merge_target_item_id",
                        "rationale",
                        "confidence",
                        "members",
                    ],
                    "properties": {
                        "cluster_id": {"type": "string"},
                        "label": {"type": "string"},
                        "angle_hint": {"type": "string"},
                        "member_ids": {"type": "array", "items": {"type": "string"}},
                        "suggested_action": {"type": "string", "enum": SUGGESTED_ACTIONS},
                        "merge_target_item_id": {"type": "string"},
                        "rationale": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "members": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["id", "reading_depth", "role_in_cluster", "one_line"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "reading_depth": {"type": "string", "enum": READING_DEPTHS},
                                    "role_in_cluster": {
                                        "type": "string",
                                        "enum": ["anchor", "support", "context"],
                                    },
                                    "one_line": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "ungrouped_ids": {"type": "array", "items": {"type": "string"}},
            "notes": {"type": "string"},
        },
    }


def record_digest(record: dict[str, Any]) -> dict[str, Any]:
    base = review_input(record)
    editorial = record.get("editorial_triage") if isinstance(record.get("editorial_triage"), dict) else {}
    return {
        "id": base["id"],
        "track": base["track"],
        "title": base["title"],
        "zh_title": clean_text(record.get("zh_title") or editorial.get("zh_title"), 200),
        "source_name": base["source_name"],
        "published_at": base["published_at"],
        "tags": base["tags"],
        "matched_keywords": base["matched_keywords"],
        "local_rule_recommendation": base["local_rule_recommendation"],
        "local_content_kind": base["local_content_kind"],
        "summary": clean_text(base["source_text"], 200),
    }


def anchor_digest(record: dict[str, Any]) -> dict[str, Any]:
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    return {
        "item_id": record.get("id"),
        "title": clean_text(record.get("title"), 200),
        "status": record.get("status"),
        "track": record.get("track"),
        "tags": record.get("tags", [])[:10] if isinstance(record.get("tags"), list) else [],
        "angle": clean_text(review.get("angle"), 160),
    }


def title_lookup(records: list[dict[str, Any]]) -> dict[str, str]:
    lookup = {}
    for record in records:
        record_id = clean_text(record.get("id"))
        if record_id:
            lookup[record_id] = clean_text(record.get("title"), 160)
    return lookup


def historical_bundles(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    """過去「真的被抓在一起」的組合：articles、compose sessions、material-links。"""
    titles = title_lookup(items)
    bundles: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()

    def add_bundle(kind: str, label: str, item_ids: list[str]) -> None:
        ids = [clean_text(value) for value in item_ids if clean_text(value)]
        key = frozenset(ids)
        if len(ids) < 2 or key in seen:
            return
        seen.add(key)
        bundles.append(
            {
                "kind": kind,
                "label": clean_text(label, 120),
                "titles": [titles.get(item_id, item_id) for item_id in ids],
            }
        )

    for article in load_jsonl(ARTICLES):
        item_ids = article.get("item_ids") if isinstance(article.get("item_ids"), list) else []
        add_bundle("published-article", article.get("title", ""), item_ids)

    for session in load_jsonl(EDITOR_SESSIONS):
        task_type = clean_text(session.get("task_type"))
        if not task_type.startswith("compose"):
            continue
        item_ids = session.get("item_ids") if isinstance(session.get("item_ids"), list) else []
        add_bundle("editor-session", session.get("title") or task_type, item_ids)

    groups: dict[str, list[str]] = {}
    for link in load_jsonl(MATERIAL_LINKS):
        left = clean_text(link.get("item_id"))
        right = clean_text(link.get("related_item_id") or link.get("target_item_id"))
        if left and right:
            groups.setdefault(left, [left]).append(right)
    for item_ids in groups.values():
        add_bundle("material-link", "同串材料", item_ids)

    return bundles[:limit]


def build_prompt(
    digests: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
    bundles: list[dict[str, Any]],
) -> str:
    taste = taste_profile_block()
    schema = cluster_schema()
    parts = [
        "你是 Ian Open News 的跨篇分流編輯。任務：把下面的候選資料依「會被同一篇文章使用」的主題分群，",
        "並替每群給建議動作、替每篇給閱讀深度。",
        "",
        "分群原則：",
        "1. 一群 = 未來可能被抓在一起寫成同一篇文章（或同一則彙報段落）的材料。不確定就不要硬湊，放進 ungrouped_ids。",
        "2. 單篇也值得收的可以自成一群（suggested_action=collect-individual）。",
        "3. 若某群明顯是某個進行中稿件的補充材料，用 merge-into-item 並填 merge_target_item_id（只能從下面的進行中稿件清單選）。",
        "4. 整群都像雜訊/公告/舊聞 → skip；拿不準 → ask。",
        "5. reading_depth 三層：news-brief（新聞小消息，掃過即可）/ knowledge-worthy（值得當知識留存）/ deep-read（值得 Ian 花時間深讀）。",
        "   這與產出形態（small-news / featured-article）不同：deep-read 不一定要成文。",
        "6. role_in_cluster：anchor（這群的核心篇）/ support（補充論據）/ context（背景）。",
        "7. 用台灣慣用語，不超譯；rationale 一句話講清楚為什麼這群會被抓在一起。",
        "",
    ]
    if taste:
        parts += [taste, ""]
    if bundles:
        parts.append("過去真的被抓在一起的組合（ground truth 範例，模仿這種聚合邏輯）：")
        for bundle in bundles:
            parts.append(f"- [{bundle['kind']}] {bundle['label']}：{'、'.join(bundle['titles'][:7])}")
        parts.append("")
    if anchors:
        parts.append("進行中稿件（merge_target_item_id 只能從這裡選）：")
        parts.append(json.dumps(anchors, ensure_ascii=False, indent=1))
        parts.append("")
    parts.append("候選資料：")
    parts.append(json.dumps(digests, ensure_ascii=False, indent=1))
    parts.append("")
    parts.append("每個候選 id 必須出現在恰好一個 cluster 的 member_ids 或 ungrouped_ids，不可遺漏、不可重複。")
    parts.append(f"只輸出符合以下 JSON Schema 的 JSON 物件，不要任何額外說明：\n{json.dumps(schema, ensure_ascii=False)}")
    return "\n".join(parts)


def run_claude(prompt: str, args: argparse.Namespace) -> dict[str, Any]:
    command = [claude_path(), "-p", prompt, "--output-format", "json"]
    if args.model:
        command += ["--model", args.model]
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=args.timeout, env=env)
    if result.returncode != 0:
        raise RuntimeError(f"claude print failed\nSTDERR:\n{result.stderr[-2000:]}")
    (ROOT / ".cache" / "triage-cluster-output.json").write_text(result.stdout, encoding="utf-8")
    return parse_cli_json(result.stdout)


def run_codex(prompt: str, args: argparse.Namespace) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    schema_path = cache / "triage-cluster.schema.json"
    output_path = cache / "triage-cluster-output.json"
    schema_path.write_text(json.dumps(cluster_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
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
    ]
    if args.model:
        command += ["-m", args.model]
    command.append("-")
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    result = subprocess.run(
        command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=args.timeout, env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f"codex exec failed\nSTDERR:\n{result.stderr[-2000:]}")
    return json.loads(output_path.read_text(encoding="utf-8"))


def validate_and_normalize(
    payload: dict[str, Any], input_ids: list[str], anchor_ids: set[str]
) -> dict[str, Any]:
    """模型輸出的防線：幻覺 id 剔除、重複成員去重、merge 目標白名單、全集補齊。"""
    input_set = set(input_ids)
    assigned: set[str] = set()
    clusters: list[dict[str, Any]] = []
    raw_clusters = payload.get("clusters") if isinstance(payload.get("clusters"), list) else []
    for index, raw in enumerate(raw_clusters, start=1):
        if not isinstance(raw, dict):
            continue
        members = []
        raw_members = raw.get("members") if isinstance(raw.get("members"), list) else []
        member_meta = {
            clean_text(member.get("id")): member for member in raw_members if isinstance(member, dict)
        }
        raw_ids = raw.get("member_ids") if isinstance(raw.get("member_ids"), list) else []
        ordered_ids = list(dict.fromkeys([clean_text(value) for value in raw_ids] + list(member_meta.keys())))
        for member_id in ordered_ids:
            if member_id not in input_set or member_id in assigned:
                continue
            meta = member_meta.get(member_id, {})
            depth = clean_text(meta.get("reading_depth"))
            role = clean_text(meta.get("role_in_cluster"))
            members.append(
                {
                    "id": member_id,
                    "reading_depth": depth if depth in READING_DEPTHS else "knowledge-worthy",
                    "role_in_cluster": role if role in {"anchor", "support", "context"} else "support",
                    "one_line": clean_text(meta.get("one_line"), 200),
                }
            )
            assigned.add(member_id)
        if not members:
            continue
        action = clean_text(raw.get("suggested_action"))
        if action not in SUGGESTED_ACTIONS:
            action = "ask"
        merge_target = clean_text(raw.get("merge_target_item_id"))
        if action == "merge-into-item" and merge_target not in anchor_ids:
            # 併稿目標是幻覺 id：降級為 ask，保留原 rationale 讓人看得出原意。
            action = "ask"
            merge_target = ""
        if action != "merge-into-item":
            merge_target = ""
        clusters.append(
            {
                "cluster_id": clean_text(raw.get("cluster_id")) or f"cluster-{index:02d}",
                "label": clean_text(raw.get("label"), 120) or f"未命名群 {index}",
                "angle_hint": clean_text(raw.get("angle_hint"), 200),
                "member_ids": [member["id"] for member in members],
                "suggested_action": action,
                "merge_target_item_id": merge_target,
                "rationale": clean_text(raw.get("rationale"), 400),
                "confidence": clean_text(raw.get("confidence")) or "low",
                "members": members,
            }
        )
    ungrouped = [record_id for record_id in input_ids if record_id not in assigned]
    return {
        "clusters": clusters,
        "ungrouped_ids": ungrouped,
        "notes": clean_text(payload.get("notes"), 400),
    }


def apply_cluster_to_records(
    result: dict[str, Any], records: list[dict[str, Any]], run_id: str, generated_at: str
) -> int:
    """把分群結果逐筆寫進 record.editorial_triage.cluster；回傳更新筆數。"""
    membership: dict[str, dict[str, Any]] = {}
    for cluster in result["clusters"]:
        for member in cluster["members"]:
            membership[member["id"]] = {
                "run_id": run_id,
                "cluster_id": cluster["cluster_id"],
                "label": cluster["label"],
                "suggested_action": cluster["suggested_action"],
                "merge_target_item_id": cluster["merge_target_item_id"],
                "reading_depth": member["reading_depth"],
                "role_in_cluster": member["role_in_cluster"],
                "generated_at": generated_at,
            }
    updated = 0
    for record in records:
        info = membership.get(clean_text(record.get("id")))
        if not info:
            continue
        editorial = record.get("editorial_triage")
        if not isinstance(editorial, dict):
            editorial = {}
            record["editorial_triage"] = editorial
        editorial["cluster"] = info
        updated += 1
    return updated


def eval_replay(args: argparse.Namespace) -> int:
    """離線評測：把某篇已發布文章的成員混入拒絕項重跑，量「被分在同群」召回率。"""
    articles = load_jsonl(ARTICLES)
    articles = [a for a in articles if isinstance(a.get("item_ids"), list) and len(a["item_ids"]) >= 3]
    if not articles:
        print("沒有 item_ids >= 3 的文章可評測。")
        return 1
    article = articles[0] if not args.eval_article_id else next(
        (a for a in articles if a.get("id") == args.eval_article_id), articles[0]
    )
    items = load_jsonl(ITEMS)
    by_id = {clean_text(item.get("id")): item for item in items}
    truth_records = [by_id[i] for i in article["item_ids"] if i in by_id]
    if len(truth_records) < 3:
        print("該文章的 item 已不在 items.jsonl，無法評測。")
        return 1
    rejected = load_jsonl(REJECTED_ITEMS)
    random.seed(20260705)
    noise = random.sample(rejected, min(20, len(rejected)))
    pool = truth_records + noise
    random.shuffle(pool)
    digests = [record_digest(record) for record in pool]
    prompt = build_prompt(digests, [], historical_bundles(items))
    payload = run_claude(prompt, args) if args.engine == "claude" else run_codex(prompt, args)
    result = validate_and_normalize(payload, [d["id"] for d in digests], set())
    truth_ids = {clean_text(r.get("id")) for r in truth_records}
    best_overlap = 0
    for cluster in result["clusters"]:
        overlap = len(truth_ids & set(cluster["member_ids"]))
        best_overlap = max(best_overlap, overlap)
    recall = best_overlap / len(truth_ids)
    print(f"評測文章：{clean_text(article.get('title'), 80)}")
    print(f"ground truth {len(truth_ids)} 篇混入 {len(noise)} 篇拒絕項")
    print(f"最佳同群召回率：{best_overlap}/{len(truth_ids)} = {recall:.0%}")
    (ROOT / ".cache" / "triage-cluster-eval.json").write_text(
        json.dumps({"article": article.get("id"), "recall": recall, "result": result}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="跨篇分群分流（AI 分堆+預選，落地由人批次確認）")
    parser.add_argument("--engine", choices=CLUSTER_ENGINES, default="claude")
    parser.add_argument("--model", default="", help="選用：指定引擎的模型（不帶 = 引擎預設）")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--track", default="", help="只分某條主線")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--status-file", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="只寫 preview 檔，不回寫任何紀錄")
    parser.add_argument("--eval-replay", action="store_true", help="離線評測分群召回率")
    parser.add_argument("--eval-article-id", default="")
    args = parser.parse_args()

    if args.eval_replay:
        return eval_replay(args)

    write_status(args.status_file, {"phase": "loading", "message": "讀取候選與稿件"})
    candidates = load_jsonl(CANDIDATES)
    items = load_jsonl(ITEMS)

    pending = [c for c in candidates if clean_text(c.get("candidate_status")) == "pending"]
    inbox = [i for i in items if clean_text(i.get("status")) == "inbox"]
    if args.track:
        pending = [c for c in pending if clean_text(c.get("track")) == args.track]
        inbox = [i for i in inbox if clean_text(i.get("track")) == args.track]
    pool = pending + inbox
    if not pool:
        write_status(args.status_file, {"phase": "done", "message": "沒有待分群的候選"})
        print("沒有 pending 候選或 inbox item，無事可做。")
        return 0
    if len(pool) > args.limit:
        # 超量時先分「規則建議收/待看」者，其餘留給下一輪。
        def priority(record: dict[str, Any]) -> int:
            rec = clean_text((record.get("triage") or {}).get("recommendation"))
            return {"suggest-collect": 0, "suggest-review": 1, "suggest-ask": 2}.get(rec, 3)

        pool = sorted(pool, key=priority)[: args.limit]

    anchors = [anchor_digest(i) for i in items if clean_text(i.get("status")) in ANCHOR_STATUSES]
    anchor_ids = {a["item_id"] for a in anchors}
    bundles = historical_bundles(items)
    digests = [record_digest(record) for record in pool]
    input_ids = [d["id"] for d in digests]

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = "clu-" + hashlib.sha256(f"{generated_at}-{len(pool)}".encode()).hexdigest()[:12]
    write_status(
        args.status_file,
        {"phase": "clustering", "message": f"以 {args.engine} 分群 {len(pool)} 筆", "run_id": run_id},
    )
    prompt = build_prompt(digests, anchors, bundles)
    payload = run_claude(prompt, args) if args.engine == "claude" else run_codex(prompt, args)
    result = validate_and_normalize(payload, input_ids, anchor_ids)

    output = {
        "run_id": run_id,
        "generated_at": generated_at,
        "engine": args.engine,
        "model": args.model,
        "input_scope": {"pending": len(pending), "inbox": len(inbox), "clustered": len(pool), "track": args.track},
        **result,
    }
    if args.dry_run:
        CLUSTERS_PREVIEW.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"dry-run：{len(result['clusters'])} 群 / ungrouped {len(result['ungrouped_ids'])} → {CLUSTERS_PREVIEW}")
        return 0

    CLUSTERS_LATEST.write_text(json.dumps(output, ensure_ascii=False, indent=1), encoding="utf-8")
    with CLUSTERS_RUNS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(output, ensure_ascii=False) + "\n")

    updated_candidates = apply_cluster_to_records(result, candidates, run_id, generated_at)
    updated_items = apply_cluster_to_records(result, items, run_id, generated_at)
    if updated_candidates:
        write_jsonl(CANDIDATES, candidates)
    if updated_items:
        write_jsonl(ITEMS, items)

    write_status(
        args.status_file,
        {
            "phase": "done",
            "message": f"分成 {len(result['clusters'])} 群（候選 {updated_candidates} 筆、item {updated_items} 筆已標記）",
            "run_id": run_id,
        },
    )
    print(
        f"run {run_id}：{len(result['clusters'])} 群、ungrouped {len(result['ungrouped_ids'])}；"
        f"回寫候選 {updated_candidates} 筆、items {updated_items} 筆。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
