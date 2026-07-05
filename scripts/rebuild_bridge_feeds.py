#!/usr/bin/env python3
"""批次重組 bridge 來源的 feed_url。

bridge（例如自架 RSSHub）換主機或 port 時，sources.jsonl 裡同一個
served_via 的來源會有 N 筆 feed_url 要改。這支 script 一次改完：
保留各 feed_url 原本的 path 與 query，只換 base URL。

其他行（served_via 不符或沒有 served_via 的來源）一個 byte 都不動，
維持一筆一行方便 PR 逐行 review。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "database" / "sources.jsonl"


def rebuild_feed_url(old_feed_url: str, base: str) -> str:
    """保留舊 feed_url 的 path 與 query，換成新的 base URL。"""
    parsed = urlparse(old_feed_url)
    new_url = base.rstrip("/") + parsed.path
    if parsed.query:
        new_url += "?" + parsed.query
    return new_url


def main() -> None:
    parser = argparse.ArgumentParser(description="bridge 換主機時批次重組 sources.jsonl 的 feed_url。")
    parser.add_argument("--served-via", required=True, help="要處理的 served_via 值，例如 rsshub@local")
    parser.add_argument("--base", required=True, help="新的 base URL，例如 http://127.0.0.1:1200")
    parser.add_argument("--sources", type=Path, default=SOURCES)
    parser.add_argument("--dry-run", action="store_true", help="只印出「舊 → 新」對照，不寫檔")
    args = parser.parse_args()

    if not args.sources.exists():
        raise SystemExit(f"找不到來源檔：{args.sources}")

    # 逐行處理：只重寫 served_via 相符的行，其他行原封不動（含空行與行序）。
    raw_lines = args.sources.read_text(encoding="utf-8").split("\n")
    output_lines = []
    changed = 0
    matched = 0
    for line_number, line in enumerate(raw_lines, start=1):
        if not line.strip():
            output_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"警告：跳過無法解析的行 {args.sources}:{line_number}: {exc}")
            output_lines.append(line)
            continue
        if record.get("served_via") != args.served_via:
            output_lines.append(line)
            continue
        matched += 1
        old_feed_url = str(record.get("feed_url") or "")
        new_feed_url = rebuild_feed_url(old_feed_url, args.base)
        if new_feed_url == old_feed_url:
            output_lines.append(line)
            continue
        changed += 1
        name = record.get("name") or record.get("id") or f"line {line_number}"
        print(f"{name}: {old_feed_url} → {new_feed_url}")
        record["feed_url"] = new_feed_url
        # 與 analyze_source_health.write_jsonl 相同的序列化方式，維持欄位順序穩定。
        output_lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))

    if matched == 0:
        print(f"沒有任何來源的 served_via 等於 {args.served_via!r}，不需要改動。")
        raise SystemExit(0)

    if args.dry_run:
        print(f"dry run：served_via={args.served_via} 共 {matched} 筆，其中 {changed} 筆 feed_url 會改動（未寫檔）。")
        return

    if changed == 0:
        print(f"served_via={args.served_via} 共 {matched} 筆，feed_url 都已是新 base，不需寫檔。")
        return

    args.sources.write_text("\n".join(output_lines), encoding="utf-8")
    print(f"完成：served_via={args.served_via} 共 {matched} 筆，改了 {changed} 筆 feed_url，已寫回 {args.sources}。")


if __name__ == "__main__":
    main()
