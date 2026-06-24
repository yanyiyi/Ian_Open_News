#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from codex_enrich_reviews import agy_path, claude_path, codex_path, load_json_from_text


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
STATUS = ROOT / ".cache" / "pdf-split-status.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_markdown(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def item_markdown(item: dict[str, Any]) -> str:
    metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
    for key in (
        "translated_article_markdown_zh",
        "codex_translated_article_markdown_zh",
        "claude_translated_article_markdown_zh",
        "gemini_translated_article_markdown_zh",
        "article_markdown",
        "article_text",
    ):
        text = clean_markdown(metadata.get(key))
        if text:
            return text
    return clean_markdown(item.get("summary"))


def output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["proposal"],
        "properties": {
            "proposal": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "sections"],
                "properties": {
                    "summary": {"type": "string"},
                    "sections": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["title", "start_marker", "end_marker", "notes"],
                            "properties": {
                                "title": {"type": "string"},
                                "start_marker": {"type": "string"},
                                "end_marker": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                },
            }
        },
    }


def build_prompt(item: dict[str, Any], markdown: str) -> str:
    schema = output_schema()
    return f"""你是 Ian Open News 的 PDF 材料拆分助理。

請判斷下列 PDF Markdown 是否包含多篇可獨立入庫的文章、章節或報告單元，並提出一份拆分草案。

規則：
- 只根據提供的全文，不上網，不補不存在的內容。
- 每一篇都要給 title、start_marker、end_marker。
- start_marker 與 end_marker 必須逐字取自全文，選 15 到 100 個字、能唯一定位的起始句與結束句。
- 起訖標記要涵蓋該篇完整內容；不要只給頁碼或「Introduction」這類重複短詞。
- 若前言、目錄、版權頁不適合成為獨立材料，不必硬拆。
- 這只是人工核對草案，不要自行修改資料庫或產生 article。
- sections 至少兩篇；若其實不適合拆，仍列出最合理的內容單元，並在 summary 說明限制。

PDF 材料：
- id: {item.get("id", "")}
- title: {item.get("title", "")}

回覆只能是符合以下 JSON Schema 的 JSON，不要 Markdown 包裝：
{json.dumps(schema, ensure_ascii=False, indent=2)}

全文：
{markdown}
"""


def generic_payload(raw: str) -> dict[str, Any]:
    payload = load_json_from_text(raw)
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        nested = load_json_from_text(payload["result"])
        if isinstance(nested, dict):
            return nested
    if isinstance(payload, dict):
        return payload
    raise RuntimeError("CLI output missing JSON object")


def run_provider(provider: str, prompt: str, timeout: int) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    if provider == "codex":
        schema_path = cache / "pdf-split.schema.json"
        output_path = cache / "pdf-split-codex-output.json"
        schema_path.write_text(json.dumps(output_schema(), ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            codex_path(), "-a", "never", "exec", "--ephemeral", "--cd", str(ROOT),
            "--sandbox", "read-only", "--color", "never",
            "--output-schema", str(schema_path), "--output-last-message", str(output_path), "-",
        ]
        result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=env)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Codex 執行失敗")[-2400:])
        return generic_payload(output_path.read_text(encoding="utf-8"))
    if provider == "claude":
        command = [claude_path(), "-p", prompt, "--output-format", "json"]
    elif provider == "gemini":
        command = [agy_path(), "--print", prompt]
    else:
        raise RuntimeError(f"不支援的 provider：{provider}")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, env=env)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"{provider} 執行失敗")[-2400:])
    return generic_payload(result.stdout)


def validate_proposal(payload: dict[str, Any], markdown: str) -> dict[str, Any]:
    proposal = payload.get("proposal") if isinstance(payload.get("proposal"), dict) else {}
    sections = proposal.get("sections") if isinstance(proposal.get("sections"), list) else []
    cleaned = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        start_marker = str(section.get("start_marker") or "").strip()
        end_marker = str(section.get("end_marker") or "").strip()
        if not title or not start_marker or not end_marker:
            continue
        cleaned.append(
            {
                "title": title[:320],
                "start_marker": start_marker[:500],
                "end_marker": end_marker[:500],
                "notes": str(section.get("notes") or "").strip()[:800],
                "start_found": start_marker in markdown,
                "end_found": end_marker in markdown,
            }
        )
    if len(cleaned) < 2:
        raise RuntimeError("CLI 沒有回傳至少兩篇可用的拆分區段。")
    return {"summary": str(proposal.get("summary") or "").strip()[:1600], "sections": cleaned}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask one local AI CLI for a PDF split proposal.")
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--provider", choices=["codex", "claude", "gemini"], required=True)
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--status-file", type=Path, default=STATUS)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()

    records = load_jsonl(args.items)
    item = next((record for record in records if str(record.get("id") or "") == args.item_id), None)
    if not item:
        raise SystemExit(f"找不到 item：{args.item_id}")
    markdown = item_markdown(item)
    if len(markdown) < 500:
        raise SystemExit("PDF 全文不足，無法提出拆分建議。")

    write_status(args.status_file, {"state": "running", "item_id": args.item_id, "provider": args.provider, "message": "正在閱讀 PDF 全文並提出拆分草案。"})
    try:
        payload = run_provider(args.provider, build_prompt(item, markdown), args.timeout)
        proposal = validate_proposal(payload, markdown)
        metadata = item.get("reading_metadata") if isinstance(item.get("reading_metadata"), dict) else {}
        proposals = metadata.get("pdf_split_proposals") if isinstance(metadata.get("pdf_split_proposals"), dict) else {}
        proposals = dict(proposals)
        proposals[args.provider] = proposal
        metadata = {**metadata, "pdf_split_proposals": proposals}
        updated = {**item, "reading_metadata": metadata}
        write_jsonl(args.items, [updated if record.get("id") == args.item_id else record for record in records])
        write_status(args.status_file, {"state": "done", "item_id": args.item_id, "provider": args.provider, "message": "拆分草案完成。", "section_count": len(proposal["sections"])})
        print(json.dumps({"ok": True, "provider": args.provider, "proposal": proposal}, ensure_ascii=False))
    except Exception as exc:
        write_status(args.status_file, {"state": "failed", "item_id": args.item_id, "provider": args.provider, "message": str(exc)})
        raise


if __name__ == "__main__":
    main()
