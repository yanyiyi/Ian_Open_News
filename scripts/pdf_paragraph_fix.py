#!/usr/bin/env python3
"""用快速 AI 把「缺段落結構」的 PDF 全文重新分段（只重排換行與標題，不改字詞）。

對齊三引擎韌性：先試指定引擎，失敗再換其他可用引擎。輸出 JSON 到 stdout 給
local_web.py 的 /items/repaginate-fulltext 解析。內建防呆：重排後字數若和原文差太多就判失敗。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "database" / "items.jsonl"
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"

PROVIDER_LABELS = {"codex": "Codex", "claude": "Claude Code", "gemini": "Gemini (agy)"}


def load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def find_record(item_id: str) -> dict | None:
    for path in (ITEMS, CANDIDATES):
        for row in load_jsonl(path):
            if str(row.get("id") or "") == item_id:
                return row
    return None


def item_fulltext(record: dict) -> str:
    metadata = record.get("reading_metadata") if isinstance(record.get("reading_metadata"), dict) else {}
    for key in ("article_markdown", "article_text"):
        text = str(metadata.get(key) or "").strip()
        if len(text) >= 200:
            return text
    return str(record.get("summary") or "").strip()


def _resolve(name: str, fallbacks: list[str]) -> str:
    found = shutil.which(name)
    if found:
        return found
    for path in [str(Path.home() / ".local" / "bin" / name), *fallbacks]:
        if Path(path).exists():
            return path
    raise RuntimeError(f"找不到 {name} CLI。")


def codex_path() -> str:
    return _resolve("codex", ["/opt/homebrew/bin/codex", "/usr/local/bin/codex"])


def claude_path() -> str:
    return _resolve("claude", ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"])


def agy_path() -> str:
    return _resolve("agy", ["/opt/homebrew/bin/agy", "/usr/local/bin/agy"])


def available_providers() -> list[str]:
    out = []
    for provider, finder in [("claude", claude_path), ("codex", codex_path), ("gemini", agy_path)]:
        try:
            finder()
        except RuntimeError:
            continue
        out.append(provider)
    return out


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + str(Path.home() / ".local" / "bin") + ":" + env.get("PATH", "")
    return env


def build_prompt(text: str) -> str:
    body = text[:40000]
    return (
        "你是中文排版助理。下面是一份缺乏段落結構的全文。請只做兩件事：\n"
        "1. 依語意在適當位置插入空行，把長段落分成好讀的段落。\n"
        "2. 把明顯是標題的行改成 markdown 標題（# 或 ##）。\n"
        "嚴格規則：**絕對不要改動、增加、刪除或翻譯任何文字內容**，只能調整換行、空行與標題標記。\n"
        "直接輸出處理後的 markdown 全文，不要加任何說明、前言或程式碼框。\n\n"
        f"全文開始>>>\n{body}\n<<<全文結束"
    )


def strip_wrapping(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    return text


def alnum_signature(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z㐀-鿿]", text))


def run_claude(prompt: str, timeout: int) -> str:
    command = [
        claude_path(), "--print", "--input-format", "text", "--output-format", "text",
        "--no-session-persistence", "--permission-mode", "dontAsk", "--tools", "",
    ]
    result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=base_env())
    if result.returncode != 0:
        raise RuntimeError(f"claude failed\n{result.stderr[-800:]}")
    return result.stdout


def run_codex(prompt: str, timeout: int) -> str:
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    output_path = cache / "pdf-repaginate-output.txt"
    command = [
        codex_path(), "-a", "never", "exec", "--ephemeral", "--cd", str(ROOT),
        "--sandbox", "read-only", "--color", "never", "--output-last-message", str(output_path), "-",
    ]
    result = subprocess.run(command, cwd=ROOT, input=prompt, text=True, capture_output=True, timeout=timeout, env=base_env())
    if result.returncode != 0:
        raise RuntimeError(f"codex failed\n{result.stderr[-800:]}")
    return output_path.read_text(encoding="utf-8")


def run_gemini(prompt: str, timeout: int) -> str:
    command = [agy_path(), "--print", prompt]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, env=base_env())
    if result.returncode != 0:
        raise RuntimeError(f"agy failed\n{result.stderr[-800:]}")
    return result.stdout


def run_provider(provider: str, prompt: str, timeout: int) -> str:
    if provider == "codex":
        return run_codex(prompt, timeout)
    if provider == "gemini":
        return run_gemini(prompt, timeout)
    return run_claude(prompt, timeout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True)
    parser.add_argument("--provider", default="claude")
    parser.add_argument("--timeout", type=int, default=480)
    args = parser.parse_args()

    record = find_record(args.id)
    if not record:
        print(json.dumps({"ok": False, "errors": ["找不到項目。"]}, ensure_ascii=False))
        return 1
    text = item_fulltext(record)
    if len(text) < 200:
        print(json.dumps({"ok": False, "errors": ["全文太短，不需要重新分段。"]}, ensure_ascii=False))
        return 1

    prompt = build_prompt(text)
    base_sig = alnum_signature(text[:40000])
    order = [args.provider] + [p for p in available_providers() if p != args.provider]
    seen = set()
    errors = []
    for provider in order:
        if provider in seen:
            continue
        seen.add(provider)
        try:
            raw = run_provider(provider, prompt, args.timeout)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{PROVIDER_LABELS.get(provider, provider)}：{str(exc)[:200]}")
            continue
        markdown = strip_wrapping(raw)
        sig = alnum_signature(markdown)
        # 防呆：重排後實際字元數不可和原文差超過 12%（避免模型偷改/截斷）。
        if base_sig and abs(sig - base_sig) / base_sig > 0.12:
            errors.append(f"{PROVIDER_LABELS.get(provider, provider)}：輸出字數與原文差太多，已略過。")
            continue
        if len(markdown) < 200:
            errors.append(f"{PROVIDER_LABELS.get(provider, provider)}：輸出太短。")
            continue
        print(json.dumps({"ok": True, "provider": PROVIDER_LABELS.get(provider, provider), "markdown": markdown, "errors": errors}, ensure_ascii=False))
        return 0

    print(json.dumps({"ok": False, "markdown": "", "errors": errors or ["沒有可用的 AI 引擎。"]}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
