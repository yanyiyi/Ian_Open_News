#!/usr/bin/env python3
"""解析 Perplexity 作者查證結果，回填 database/authors.jsonl 與 organizations.jsonl。

輸入是 Perplexity 依 batch prompt 指定 schema 輸出的 JSON 陣列（存成 .json，
或整段回覆貼成 .md 也可以——解析器會抓第一個 ```json code block，沒有就找
第一個平衡的 [...]，並容忍 trailing comma）。

合併規則（idempotent，可重跑）：
- name 比對回 authors.jsonl（byline/name 正規化比對）；比對不到列進報告，不硬塞。
- verification.status 已是 verified 的實體不覆寫（人工確認過的優先）。
- kind/intro_zh/links 只在查證結果有值時更新；org 名稱比對 organizations.jsonl
  （name/aliases），沒有就建新實體，並回填 author.org_ids。
- confidence=low 或 kind=unknown → 標 needs-review，其餘標 ai-suggested。
- 檔案順序保持不動（新組織附加在檔尾），git diff 只出現真的動過的行。

用法：
    python3 scripts/import_author_research.py --input .cache/author-research/batch-01-result.json
    python3 scripts/import_author_research.py --input result.md --method perplexity-single
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import author_registry as ar

_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")


def _find_balanced_array(text: str) -> str:
    start = text.find("[")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for pos in range(start, len(text)):
            char = text[pos]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return text[start:pos + 1]
        start = text.find("[", start + 1)
    return ""


def parse_research_payload(text: str) -> list[dict]:
    """從 Perplexity 回覆（或純 JSON）撈出查證結果陣列；解析不了就丟 ValueError。"""
    candidates = [match.strip() for match in _JSON_BLOCK_RE.findall(text)]
    candidates.append(text.strip())
    array = _find_balanced_array(text)
    if array:
        candidates.append(array)
    for candidate in candidates:
        if not candidate:
            continue
        for attempt in (candidate, _TRAILING_COMMA_RE.sub(r"\1", candidate)):
            try:
                payload = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, list):
                entries = [entry for entry in payload if isinstance(entry, dict) and entry.get("name")]
                if entries:
                    return entries
            if isinstance(payload, dict) and payload.get("name"):
                return [payload]
    raise ValueError("找不到可解析的 JSON 陣列（要有 name 欄位的物件）")


def _find_org(name: str, organizations: list[dict]) -> dict | None:
    key = ar.normalize_byline(name)
    if not key:
        return None
    for org in organizations:
        candidates = [org.get("name", "")] + list(org.get("aliases") or [])
        if any(ar.normalize_byline(alias) == key for alias in candidates):
            return org
    return None


def apply_research_entries(
    entries: list[dict],
    *,
    evidence: str,
    method: str = "perplexity-batch",
) -> dict:
    """把查證結果 merge 進 authors/organizations.jsonl，回傳統計報告。"""
    authors = ar.load_authors()
    organizations = ar.load_organizations()
    index = ar.build_author_index(authors)
    now = ar.now_utc_iso()
    today = now[:10]
    report = {"updated": [], "skipped_verified": [], "unmatched": [], "needs_review": [], "orgs_created": []}

    for entry in entries:
        name = str(entry.get("name") or "").strip()
        author = index.get(ar.normalize_byline(name))
        if author is None:
            report["unmatched"].append(name)
            continue
        if (author.get("verification") or {}).get("status") == "verified":
            report["skipped_verified"].append(author["name"])
            continue

        kind = str(entry.get("kind") or "").strip()
        if kind in ar.AUTHOR_KINDS:
            author["kind"] = kind
        intro = str(entry.get("intro_zh") or "").strip()
        if intro:
            author["intro_zh"] = intro
        links = author.setdefault("links", [])
        for link in entry.get("links") or []:
            link = str(link or "").strip()
            if link and link not in links:
                links.append(link)
        note = str(entry.get("note") or "").strip()
        if note and note not in str(author.get("notes") or ""):
            existing_notes = str(author.get("notes") or "").strip()
            author["notes"] = f"{existing_notes}\n{note}".strip()

        org_name = str(entry.get("org") or "").strip()
        if org_name:
            org = _find_org(org_name, organizations)
            if org is None:
                org = ar.new_org_record(org_name)
                org_intro = str(entry.get("org_intro_zh") or "").strip()
                if org_intro:
                    org["intro_zh"] = org_intro
                org_url = str(entry.get("org_url") or "").strip()
                if org_url:
                    org["links"].append(org_url)
                org["verification"] = {
                    "status": "ai-suggested", "checked_at": today,
                    "method": method, "evidence": evidence,
                }
                organizations.append(org)
                report["orgs_created"].append(org["name"])
            else:
                if not org.get("intro_zh") and str(entry.get("org_intro_zh") or "").strip():
                    org["intro_zh"] = str(entry["org_intro_zh"]).strip()
                    org["updated_at"] = now
                org_url = str(entry.get("org_url") or "").strip()
                org_links = org.setdefault("links", [])
                if org_url and org_url not in org_links:
                    org_links.append(org_url)
                    org["updated_at"] = now
            org_ids = author.setdefault("org_ids", [])
            if org["id"] not in org_ids:
                org_ids.append(org["id"])

        confidence = str(entry.get("confidence") or "").strip().lower()
        status = "needs-review" if confidence == "low" or author["kind"] == "unknown" else "ai-suggested"
        author["verification"] = {
            "status": status, "checked_at": today, "method": method, "evidence": evidence,
        }
        author["updated_at"] = now
        report["updated"].append(author["name"])
        if status == "needs-review":
            report["needs_review"].append(author["name"])

    ar.write_jsonl(ar.AUTHORS_PATH, authors)
    ar.write_jsonl(ar.ORGANIZATIONS_PATH, organizations)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Perplexity 結果檔（.json 或整段回覆 .md）")
    parser.add_argument("--method", default="perplexity-batch",
                        choices=list(ar.VERIFICATION_METHODS), help="查證方式（記進 verification.method）")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"找不到輸入檔：{input_path}", file=sys.stderr)
        return 1
    try:
        entries = parse_research_payload(input_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"解析失敗：{exc}", file=sys.stderr)
        return 1

    evidence = str(input_path)
    if evidence.startswith(str(ar.ROOT)):
        evidence = str(input_path.resolve().relative_to(ar.ROOT))
    report = apply_research_entries(entries, evidence=evidence, method=args.method)

    print(f"讀入 {len(entries)} 筆查證結果")
    print(f"  更新作者：{len(report['updated'])}")
    if report["orgs_created"]:
        print(f"  新建組織：{len(report['orgs_created'])} — {'、'.join(report['orgs_created'])}")
    if report["needs_review"]:
        print(f"  待人工複核（low confidence / unknown）：{'、'.join(report['needs_review'])}")
    if report["skipped_verified"]:
        print(f"  已人工確認、略過：{'、'.join(report['skipped_verified'])}")
    if report["unmatched"]:
        print(f"  ⚠ 對不回作者庫：{'、'.join(report['unmatched'])}")
    print("記得跑 python3 scripts/validate_database.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
