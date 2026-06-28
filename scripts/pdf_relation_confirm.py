#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from codex_enrich_reviews import agy_path, claude_path, codex_path, load_json_from_text, ollama_model, ollama_path
from pdf_materials import item_comparison_text, item_title


ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["relation", "confidence", "explanation"],
        "properties": {
            "relation": {"type": "string", "enum": ["same-source", "full-source", "subset", "related", "unrelated"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "explanation": {"type": "string"},
        },
    }


def parse_payload(raw: str) -> dict[str, Any]:
    payload = load_json_from_text(raw)
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        payload = load_json_from_text(payload["result"])
    if not isinstance(payload, dict):
        raise RuntimeError("CLI output missing JSON object")
    return payload


def run(provider: str, prompt: str, timeout: int) -> dict[str, Any]:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    if provider == "codex":
        schema_path = cache / "pdf-relation.schema.json"
        output_path = cache / "pdf-relation-codex-output.json"
        schema_path.write_text(json.dumps(schema(), ensure_ascii=False, indent=2), encoding="utf-8")
        command = [
            codex_path(), "-a", "never", "exec", "--ephemeral", "--cd", str(ROOT),
            "--sandbox", "read-only", "--color", "never",
            "--output-schema", str(schema_path), "--output-last-message", str(output_path), "-",
        ]
        result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=env)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "Codex 執行失敗")[-2400:])
        return parse_payload(output_path.read_text(encoding="utf-8"))
    if provider == "claude":
        command = [claude_path(), "-p", prompt, "--output-format", "json"]
        stdin_data = None
    elif provider == "gemini":
        command = [agy_path(), "--print", prompt]
        stdin_data = None
    elif provider.startswith("ollama"):
        command = [ollama_path(), "run", ollama_model(provider), "--format", "json", "--nowordwrap", "--hidethinking"]
        stdin_data = prompt
    else:
        raise RuntimeError(f"不支援的 provider：{provider}")
    result = subprocess.run(command, cwd=ROOT, input=stdin_data, text=True, capture_output=True, timeout=timeout, env=env)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or f"{provider} 執行失敗")[-2400:])
    return parse_payload(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Use one local AI CLI to confirm the relationship between a PDF item and another material.")
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--provider", choices=["codex", "claude", "gemini", "ollama", "ollama-gemma4", "ollama-twinkle"], required=True)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()

    records = load_jsonl(ITEMS)
    pdf_item = next((record for record in records if record.get("id") == args.item_id), None)
    candidate = next((record for record in records if record.get("id") == args.candidate_id), None)
    if not pdf_item or not candidate:
        raise SystemExit("找不到 PDF 或候選材料。")
    pdf_text = item_comparison_text(pdf_item)
    candidate_text = item_comparison_text(candidate)
    if len(pdf_text) < 120 or len(candidate_text) < 80:
        raise SystemExit("兩邊文字不足，無法用 CLI 確認。")
    prompt = f"""你是 Ian Open News 的材料關係確認助理。只根據下列兩份文字，判斷關係。

relation 只能選：
- same-source：同一篇或同一份內容的不同載體
- full-source：A 是 B 的完整全文或原文來源
- subset：其中一份是另一份的節錄、子篇或子集
- related：主題相關，但不是相同或包含關係
- unrelated：沒有足夠關係

不要上網，不要編造來源。回覆只能是符合 JSON Schema 的 JSON：
{json.dumps(schema(), ensure_ascii=False, indent=2)}

A（PDF）
標題：{item_title(pdf_item)}
文字：
{pdf_text}

B（既有材料）
標題：{item_title(candidate)}
文字：
{candidate_text}
"""
    result = run(args.provider, prompt, args.timeout)
    relation = str(result.get("relation") or "")
    if relation not in {"same-source", "full-source", "subset", "related", "unrelated"}:
        raise SystemExit("CLI 回傳了不支援的關係。")
    reference = pdf_item.get("reference") if isinstance(pdf_item.get("reference"), dict) else {}
    confirmations = reference.get("pdf_relation_confirmations") if isinstance(reference.get("pdf_relation_confirmations"), dict) else {}
    confirmations = dict(confirmations)
    by_candidate = confirmations.get(args.candidate_id) if isinstance(confirmations.get(args.candidate_id), dict) else {}
    confirmations[args.candidate_id] = {**by_candidate, args.provider: result}
    updated = {**pdf_item, "reference": {**reference, "pdf_relation_confirmations": confirmations}}
    write_jsonl(ITEMS, [updated if record.get("id") == args.item_id else record for record in records])
    print(json.dumps({"ok": True, "provider": args.provider, "result": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
