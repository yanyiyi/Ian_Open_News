#!/usr/bin/env python3
"""掃 items.jsonl 建初版 database/authors.jsonl，並產 Perplexity 批次查證 prompt。

- byline 取值與切分規則全走 author_registry，跟 local_web 顯示端同一把尺。
- 可重跑：既有實體只擴充 byline_names，不覆寫 intro/kind/verification
  （Perplexity 回填過的資料不會被重建洗掉）。
- 優先查證名單：出現 ≥2 篇（實測「已進可用材料區/閱讀區」條件不具篩選力——
  庫裡大多數 item 都是 triaged 以上，該條件會圈出 344 名；≥2 篇為 123 名，
  正好落在第一波要的 100–150 規模，且批次按出現次數排序、高頻作者先查）。
- 批次 prompt 寫到 .cache/author-research/batch-NN.md，每批附出處脈絡。

用法：
    python3 scripts/build_author_registry.py             # 建庫 + 產 prompt
    python3 scripts/build_author_registry.py --stats     # 只看統計不寫檔
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import author_registry as ar

ITEMS_PATH = ar.ROOT / "database" / "items.jsonl"
RESEARCH_DIR = ar.ROOT / ".cache" / "author-research"
BATCH_SIZE = 18
PRIORITY_MIN_ITEMS = 2


PROMPT_HEADER = """# 作者查證 batch {batch_no}（共 {total} 名）

把下方 `## Prompt` 整段貼進 https://www.perplexity.ai/ ，
回覆的 ```json 區塊存成 `.cache/author-research/batch-{batch_no}-result.json`
（或整段回覆直接貼回 Claude Code 也可以），然後跑：

    python3 scripts/import_author_research.py --input .cache/author-research/batch-{batch_no}-result.json

## Prompt

你是嚴謹的研究助理。以下名單是新聞/部落格文章的署名（byline），每個名字附上它出現的媒體與文章範例。請逐一查證：

1. 判斷署名是「person」（人）、「organization」（組織/媒體/機構帳號）還是「unknown」（查不到可靠資訊）。
2. 若是人：一句繁體中文介紹（現職職稱與領域）、主要所屬組織（現職優先）、1–2 個代表性連結（個人頁/機構頁/LinkedIn 擇優）。
3. 若是組織：一句繁體中文介紹＋官網。
4. 所屬組織也附一句繁體中文介紹與官網。
5. org 欄位用該組織「最常用的簡短正式名稱」（例：The GovLab、Open Source For You），不要塞括號補充、母公司或多個名稱——那些放 note。
6. 查不到就標 unknown、intro 留空——寧缺勿錯，禁止推測或編造。
7. confidence：high＝多個獨立來源一致；medium＝單一可靠來源；low＝資訊薄弱或可能同名混淆。
8. 若查到的人跟名單附的媒體領域對不上（疑似同名不同人），標 low 並在 note 說明。

輸出：只輸出一個 ```json code block，內容為 JSON 陣列，每個名字一個物件，欄位齊全（缺值填 "" 或 []，不要省略欄位）：
{{"name": "原始署名", "kind": "person|organization|unknown", "intro_zh": "", "org": "", "org_intro_zh": "", "org_url": "", "links": [], "confidence": "high|medium|low", "note": ""}}

名單：
"""


def load_items() -> list[dict]:
    items = []
    with ITEMS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def aggregate(items: list[dict]) -> dict[str, dict]:
    """normalized byline → 聚合資訊（名字寫法、出現 item、來源、優先旗標）。"""
    stats: dict[str, dict] = {}
    for item in items:
        raw = ar.item_byline_raw(item)
        if not raw or ar.looks_like_noise(raw):
            continue
        for part in ar.item_byline_parts(item):
            if ar.looks_like_noise(part):
                continue
            key = ar.normalize_byline(part)
            if not key:
                continue
            entry = stats.setdefault(key, {
                "names": {}, "items": [], "sources": {}, "raw_samples": set(),
            })
            entry["names"][part] = entry["names"].get(part, 0) + 1
            entry["items"].append(item)
            source = str(item.get("source_name") or "").strip()
            if source:
                entry["sources"][source] = entry["sources"].get(source, 0) + 1
            if raw.strip() != part:
                entry["raw_samples"].add(raw.strip())
    return stats


def merge_registry(stats: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """把聚合結果 merge 進 authors.jsonl；回傳（全部實體, 新建的 normalized keys）。"""
    existing = ar.load_authors()
    by_key: dict[str, dict] = {}
    for author in existing:
        for name in [author.get("name", "")] + list(author.get("byline_names") or []):
            normalized = ar.normalize_byline(name)
            if normalized:
                by_key.setdefault(normalized, author)
    created: list[str] = []
    for key, entry in stats.items():
        display = max(entry["names"], key=entry["names"].get)
        author = by_key.get(key)
        if author is None:
            author = ar.new_author_record(display)
            existing.append(author)
            by_key[key] = author
            created.append(key)
        names = author.setdefault("byline_names", [])
        for variant in entry["names"]:
            if ar.normalize_byline(variant) == key and variant not in names:
                names.append(variant)
    existing.sort(key=lambda a: (a.get("kind", ""), ar.normalize_byline(a.get("name", ""))))
    return existing, created


def write_batches(stats: dict[str, dict], authors: list[dict]) -> list[Path]:
    """優先名單切批產 prompt 檔；已有 intro 或已標 noise 的實體不重查。"""
    index = ar.build_author_index(authors)
    candidates = []
    for key, entry in stats.items():
        author = index.get(key)
        if author is None or author.get("kind") == "noise" or author.get("intro_zh"):
            continue
        if (author.get("verification") or {}).get("status") in {"ai-suggested", "verified"}:
            continue
        count = len(entry["items"])
        if count >= PRIORITY_MIN_ITEMS:
            candidates.append((key, entry, author, count))
    candidates.sort(key=lambda row: (-row[3], ar.normalize_byline(row[2]["name"])))

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    # 編號接在已完成批次（有 result 檔）之後，避免重跑時新批次撞到舊 result 檔名
    done_numbers = [
        int(match.group(1))
        for path in RESEARCH_DIR.glob("batch-*-result.*")
        if (match := re.match(r"batch-(\d+)-result\.", path.name))
    ]
    first_no = max(done_numbers, default=0) + 1
    for stale in RESEARCH_DIR.glob("batch-*.md"):
        if re.fullmatch(r"batch-\d+\.md", stale.name):
            stale.unlink()
    paths: list[Path] = []
    for batch_no, start in enumerate(range(0, len(candidates), BATCH_SIZE), start=first_no):
        chunk = candidates[start:start + BATCH_SIZE]
        lines = [PROMPT_HEADER.format(batch_no=f"{batch_no:02d}", total=len(chunk))]
        for row_no, (key, entry, author, count) in enumerate(chunk, start=1):
            sources = sorted(entry["sources"], key=entry["sources"].get, reverse=True)[:2]
            articles = []
            for item in entry["items"][:2]:
                title = str(item.get("title") or "").strip()
                url = str(item.get("url") or "").strip()
                if title:
                    articles.append(f"「{title}」({url})" if url else f"「{title}」")
            context = []
            if sources:
                context.append(f"常出現於：{'、'.join(sources)}")
            if articles:
                context.append(f"文章例：{'；'.join(articles)}")
            raw_hint = next(iter(sorted(entry["raw_samples"])), "")
            if raw_hint and len(raw_hint) <= 120:
                context.append(f"署名原文：{raw_hint}")
            lines.append(f"{row_no}. {author['name']} — {'；'.join(context)}")
        path = RESEARCH_DIR / f"batch-{batch_no:02d}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", action="store_true", help="只看統計，不寫任何檔案")
    args = parser.parse_args()

    items = load_items()
    stats = aggregate(items)
    priority = [key for key, entry in stats.items()
                if len(entry["items"]) >= PRIORITY_MIN_ITEMS]
    print(f"items：{len(items)} 筆；不重複 byline 實體：{len(stats)}；優先查證(≥{PRIORITY_MIN_ITEMS} 篇)：{len(priority)}")
    if args.stats:
        kinds: dict[str, int] = {}
        for key in stats:
            display = max(stats[key]["names"], key=stats[key]["names"].get)
            kind = ar.guess_kind(display)
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"kind 初步猜測：{kinds}")
        return 0

    authors, created = merge_registry(stats)
    ar.write_jsonl(ar.AUTHORS_PATH, authors)
    print(f"authors.jsonl：共 {len(authors)} 筆（本次新建 {len(created)}）→ {ar.AUTHORS_PATH}")
    paths = write_batches(stats, authors)
    print(f"批次 prompt：{len(paths)} 個 → {RESEARCH_DIR}/batch-NN.md")
    for path in paths:
        print(f"  - {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
