#!/usr/bin/env python3
"""全文側檔存放層：把 items/rejected-items 的重欄位拆到 database/fulltext/<id>.json。

設計原則（拆分手術的中心約定）：
- 記憶體內的 record 形狀不變：需要全文的路徑先 hydrate，heavy 欄位就回到
  reading_metadata 原位；不需要全文的路徑直接吃瘦身主檔，零改動。
- inline 優先：record 裡已有 inline 重欄位（例如剛翻譯完還沒寫檔）就用 inline，
  側檔只是 fallback；寫檔時 dehydrate 會把 inline 抽回側檔，收斂不發散。
- 側檔一篇一檔、縮排排版：翻譯一篇只動一個小檔，git diff 乾淨、PR 好審。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULLTEXT_DIR = ROOT / "database" / "fulltext"

# 固定的重欄位；翻譯欄位靠字尾規則涵蓋所有引擎（codex/claude/gemini/ollama…）
HEAVY_FIXED_KEYS = {"article_markdown", "article_text", "edited_markdown"}
HEAVY_SUFFIX = "translated_article_markdown_zh"

_STORE_CACHE: dict[str, tuple[int, dict]] = {}


def sidecar_enabled() -> bool:
    """只有真的存在側檔後，常規寫入才自動 dehydrate。

    這避免尚未正式遷移前，使用者在 UI 改一筆資料就意外觸發整批全文拆檔。
    一次性遷移腳本會直接呼叫 dehydrate_item，不受這個保護影響。
    """
    return FULLTEXT_DIR.exists() and any(FULLTEXT_DIR.glob("*.json"))


def is_heavy_key(key: str) -> bool:
    return key in HEAVY_FIXED_KEYS or key.endswith(HEAVY_SUFFIX)


def safe_item_filename(item_id: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(item_id or "")).strip("-")
    return f"{cleaned}.json" if cleaned else ""


def fulltext_path(item_id: str) -> Path | None:
    filename = safe_item_filename(item_id)
    return FULLTEXT_DIR / filename if filename else None


def load_fulltext(item_id: str) -> dict:
    """讀一篇的側檔（mtime 快取）；沒有側檔回空 dict。"""
    path = fulltext_path(item_id)
    if path is None or not path.exists():
        return {}
    stat = path.stat()
    key = str(path)
    cached = _STORE_CACHE.get(key)
    if cached and cached[0] == stat.st_mtime_ns:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    _STORE_CACHE[key] = (stat.st_mtime_ns, payload)
    return payload


def hydrate_item(item: dict) -> dict:
    """把側檔重欄位併回 reading_metadata（就地）；inline 已有的欄位不覆蓋。"""
    if not isinstance(item, dict):
        return item
    stored = load_fulltext(str(item.get("id") or ""))
    if not stored:
        return item
    metadata = item.get("reading_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        item["reading_metadata"] = metadata
    for key, value in stored.items():
        if key not in metadata or not metadata.get(key):
            metadata[key] = value
    return item


def hydrate_items(items: list[dict]) -> list[dict]:
    for item in items:
        hydrate_item(item)
    return items


def dehydrate_item(item: dict) -> bool:
    """把 record 裡 inline 的重欄位抽出寫側檔（就地移除 inline）；回傳是否有寫側檔。

    只在 record 真的帶著 inline 重欄位時動作——正常讀寫循環中，沒被 hydrate、
    也沒被翻譯/enrich 寫入的 record 完全不會觸發側檔 IO。"""
    if not isinstance(item, dict):
        return False
    metadata = item.get("reading_metadata")
    if not isinstance(metadata, dict):
        return False
    heavy = {key: metadata[key] for key in list(metadata.keys()) if is_heavy_key(key) and metadata.get(key)}
    if not heavy:
        return False
    path = fulltext_path(str(item.get("id") or ""))
    if path is None:
        return False
    merged = dict(load_fulltext(str(item.get("id") or "")))
    merged.update(heavy)
    existing = load_fulltext(str(item.get("id") or ""))
    for key in heavy:
        metadata.pop(key, None)
    if merged == existing:
        return False  # 內容沒變就不動側檔，保持 git 乾淨
    FULLTEXT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _STORE_CACHE.pop(str(path), None)
    return True


def dehydrate_items(items: list[dict]) -> int:
    written = 0
    for item in items:
        if dehydrate_item(item):
            written += 1
    return written


def store_item_ids() -> set[str]:
    """側檔目錄裡現有的 item id（依檔名還原，供 validate 對帳）。"""
    if not FULLTEXT_DIR.exists():
        return set()
    return {path.stem for path in FULLTEXT_DIR.glob("*.json")}
