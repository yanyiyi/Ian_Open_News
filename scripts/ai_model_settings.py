#!/usr/bin/env python3
"""功能級 AI CLI / 模型設定與本機模型盤點。"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "database" / "ai-model-settings.json"

PROVIDERS = {
    "codex": {"label": "Codex", "cli": "codex"},
    "claude": {"label": "Claude Code", "cli": "claude"},
    "gemini": {"label": "Gemini / Antigravity", "cli": "agy"},
    "ollama-gemma4": {"label": "Ollama gemma4:12b MLX", "cli": "ollama"},
    "ollama-twinkle": {"label": "Ollama TwinkleAI Gemma 3 4B", "cli": "ollama"},
}

TASKS = {
    "reading_review": {"label": "AI 閱讀建議", "description": "批次摘要、收錄判斷與內容類型。"},
    "translation": {"label": "全文翻譯", "description": "外文全文翻成台灣繁體中文。"},
    "triage_cluster": {"label": "候選分群", "description": "大量候選依可能共寫主題分群。"},
    "editor_theme_check": {"label": "編輯台：選法檢查", "description": "比較主題式／彙報式寫法。"},
    "editor_compose_thematic": {"label": "編輯台：主題式撰稿", "description": "需要較穩定的長文結構。"},
    "editor_compose_digest": {"label": "編輯台：彙報式撰稿", "description": "多則材料整理成彙報。"},
    "editor_factcheck": {"label": "編輯台：查核找原文", "description": "需要搜尋與來源判斷。"},
    "editor_extract_viewpoints": {"label": "編輯台：萃取觀點", "description": "從材料抽出可重用觀點。"},
    "editor_newsletter_extract": {"label": "編輯台：電子報萃取", "description": "整理電子報內的多則材料。"},
    "pdf_relation": {"label": "PDF 關係確認", "description": "判斷 PDF 與候選材料關係。"},
    "pdf_split": {"label": "PDF 拆分草案", "description": "找出多篇合併 PDF 的起訖。"},
    "pdf_repaginate": {"label": "PDF 全文重分段", "description": "只重排段落，不改內容。"},
    "taste_retro": {"label": "決策回顧", "description": "從收／不收歷史提出規則調整。"},
    "insight_analysis": {"label": "洞察分析與套用", "description": "分析分歧報告並產生設定 patch。"},
}

# 每一家都提供 economy / balanced / premium 選項；系統預設只用前兩級。
MODEL_CATALOG = {
    "codex": [
        {"id": "gpt-5.4-mini", "tier": "economy", "label": "GPT-5.4 Mini"},
        {"id": "gpt-5.6-luna", "tier": "economy", "label": "GPT-5.6 Luna"},
        {"id": "gpt-5.4", "tier": "balanced", "label": "GPT-5.4"},
        {"id": "gpt-5.6-terra", "tier": "balanced", "label": "GPT-5.6 Terra"},
        {"id": "gpt-5.5", "tier": "premium", "label": "GPT-5.5"},
        {"id": "gpt-5.6-sol", "tier": "premium", "label": "GPT-5.6 Sol"},
    ],
    "claude": [
        {"id": "haiku", "tier": "economy", "label": "Haiku（快速）"},
        {"id": "sonnet", "tier": "balanced", "label": "Sonnet（均衡）"},
        {"id": "opus", "tier": "premium", "label": "Opus（高階）"},
        {"id": "fable", "tier": "premium", "label": "Fable（高階）"},
    ],
    "gemini": [
        {"id": "Gemini 3.5 Flash (Low)", "tier": "economy", "label": "Gemini 3.5 Flash Low"},
        {"id": "Gemini 3.5 Flash (Medium)", "tier": "economy", "label": "Gemini 3.5 Flash Medium"},
        {"id": "Gemini 3.5 Flash (High)", "tier": "balanced", "label": "Gemini 3.5 Flash High"},
        {"id": "Gemini 3.1 Pro (Low)", "tier": "balanced", "label": "Gemini 3.1 Pro Low"},
        {"id": "Gemini 3.1 Pro (High)", "tier": "premium", "label": "Gemini 3.1 Pro High"},
    ],
    "ollama-gemma4": [
        {"id": "gemma4:12b-mlx", "tier": "local", "label": "gemma4:12b MLX（本機）"},
    ],
    "ollama-twinkle": [
        {"id": "TwinkleAI/gemma-3-4B-T1-it", "tier": "local", "label": "TwinkleAI Gemma 3 4B（本機）"},
    ],
}


def _models(codex: str, claude: str, gemini: str, *, complex_task: bool = False) -> dict[str, str]:
    return {
        "codex": "gpt-5.6-terra" if complex_task else codex,
        "claude": claude,
        "gemini": gemini,
        "ollama-gemma4": "gemma4:12b-mlx",
        "ollama-twinkle": "TwinkleAI/gemma-3-4B-T1-it",
    }


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "policy": {
        "allow_premium_defaults": False,
        "note": "日常功能預設 economy / balanced；premium 只能人工明確選用。",
    },
    "tasks": {
        "reading_review": {"provider": "gemini", "models": _models("gpt-5.4-mini", "haiku", "Gemini 3.5 Flash (Low)")},
        "translation": {"provider": "gemini", "models": _models("gpt-5.4", "haiku", "Gemini 3.5 Flash (Medium)")},
        "triage_cluster": {"provider": "gemini", "models": _models("gpt-5.6-luna", "haiku", "Gemini 3.5 Flash (Medium)")},
        "editor_theme_check": {"provider": "codex", "models": _models("gpt-5.6-luna", "sonnet", "Gemini 3.5 Flash (High)")},
        "editor_compose_thematic": {"provider": "claude", "models": _models("gpt-5.6-terra", "sonnet", "Gemini 3.1 Pro (Low)", complex_task=True)},
        "editor_compose_digest": {"provider": "gemini", "models": _models("gpt-5.6-luna", "sonnet", "Gemini 3.5 Flash (Medium)")},
        "editor_factcheck": {"provider": "gemini", "models": _models("gpt-5.6-terra", "sonnet", "Gemini 3.1 Pro (Low)", complex_task=True)},
        "editor_extract_viewpoints": {"provider": "gemini", "models": _models("gpt-5.6-luna", "haiku", "Gemini 3.5 Flash (Medium)")},
        "editor_newsletter_extract": {"provider": "gemini", "models": _models("gpt-5.6-luna", "haiku", "Gemini 3.5 Flash (Medium)")},
        "pdf_relation": {"provider": "gemini", "models": _models("gpt-5.4-mini", "haiku", "Gemini 3.5 Flash (Low)")},
        "pdf_split": {"provider": "gemini", "models": _models("gpt-5.6-luna", "haiku", "Gemini 3.5 Flash (Medium)")},
        "pdf_repaginate": {"provider": "gemini", "models": _models("gpt-5.4-mini", "haiku", "Gemini 3.5 Flash (Low)")},
        "taste_retro": {"provider": "codex", "models": _models("gpt-5.6-terra", "sonnet", "Gemini 3.1 Pro (Low)", complex_task=True)},
        "insight_analysis": {"provider": "codex", "models": _models("gpt-5.6-terra", "sonnet", "Gemini 3.1 Pro (Low)", complex_task=True)},
    },
}

EDITOR_TASK_KEYS = {
    "theme-check": "editor_theme_check",
    "compose-thematic": "editor_compose_thematic",
    "compose-digest": "editor_compose_digest",
    "factcheck": "editor_factcheck",
    "extract-viewpoints": "editor_extract_viewpoints",
    "newsletter-extract": "editor_newsletter_extract",
}

_DISCOVERY_CACHE: tuple[float, dict[str, dict[str, Any]]] | None = None


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    return _merge(DEFAULT_SETTINGS, raw if isinstance(raw, dict) else {})


def task_key_for_editor(task_type: str) -> str:
    return EDITOR_TASK_KEYS.get(task_type, "editor_theme_check")


def task_provider(task_key: str, path: Path = SETTINGS_PATH) -> str:
    provider = str((load_settings(path).get("tasks", {}).get(task_key) or {}).get("provider") or "").strip()
    return provider if provider in PROVIDERS else str(DEFAULT_SETTINGS["tasks"].get(task_key, {}).get("provider") or "gemini")


def task_model(task_key: str, provider: str, override: str = "", path: Path = SETTINGS_PATH) -> str:
    if str(override or "").strip():
        return str(override).strip()
    task = load_settings(path).get("tasks", {}).get(task_key) or {}
    return str((task.get("models") or {}).get(provider) or "").strip()


def model_tier(provider: str, model: str) -> str:
    return next((row["tier"] for row in MODEL_CATALOG.get(provider, []) if row["id"] == model), "custom")


def validate_settings(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tasks = candidate.get("tasks") if isinstance(candidate.get("tasks"), dict) else {}
    allow_premium = bool((candidate.get("policy") or {}).get("allow_premium_defaults"))
    for key in TASKS:
        task = tasks.get(key) if isinstance(tasks.get(key), dict) else {}
        provider = str(task.get("provider") or "")
        if provider not in PROVIDERS:
            errors.append(f"{TASKS[key]['label']} 的預設供應商無效。")
            continue
        models = task.get("models") if isinstance(task.get("models"), dict) else {}
        for provider_key in PROVIDERS:
            model = str(models.get(provider_key) or "").strip()
            if not model:
                errors.append(f"{TASKS[key]['label']} / {PROVIDERS[provider_key]['label']} 未設定模型。")
        selected_model = str(models.get(provider) or "").strip()
        if not allow_premium and model_tier(provider, selected_model) == "premium":
            errors.append(f"{TASKS[key]['label']} 的預設模型是高階 premium；目前政策禁止。")
    return errors


def save_settings(candidate: dict[str, Any], path: Path = SETTINGS_PATH) -> dict[str, Any]:
    merged = _merge(DEFAULT_SETTINGS, candidate)
    errors = validate_settings(merged)
    if errors:
        raise ValueError("\n".join(errors))
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return merged


def _run(command: list[str], timeout: int = 12) -> str:
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or result.stderr or "").strip() if result.returncode == 0 else ""


def _cli_path(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
    ):
        if candidate.exists():
            return str(candidate)
    return ""


def _codex_models() -> tuple[list[str], str]:
    cache = Path.home() / ".codex" / "models_cache.json"
    config = Path.home() / ".codex" / "config.toml"
    models: list[str] = []
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
        models = [str(row.get("slug")) for row in payload.get("models", []) if row.get("visibility") == "list" and row.get("slug")]
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    current = ""
    try:
        match = re.search(r'^model\s*=\s*["\']([^"\']+)', config.read_text(encoding="utf-8"), re.M)
        current = match.group(1) if match else ""
    except OSError:
        pass
    return models, current


def discover_cli_models(refresh: bool = False) -> dict[str, dict[str, Any]]:
    """讀本機 CLI；失敗時仍回傳設定頁可用的靜態 catalog。"""
    global _DISCOVERY_CACHE
    if not refresh and _DISCOVERY_CACHE and time.monotonic() - _DISCOVERY_CACHE[0] < 300:
        return copy.deepcopy(_DISCOVERY_CACHE[1])
    result: dict[str, dict[str, Any]] = {}
    codex_models, codex_current = _codex_models()
    agy = _cli_path("agy")
    ollama = _cli_path("ollama")
    agy_models = [line.strip() for line in _run([agy, "models"]).splitlines() if line.strip() and not line.startswith(("I", "E"))] if agy else []
    ollama_lines = _run([ollama, "list"]).splitlines() if ollama else []
    ollama_models = [line.split()[0].removesuffix(":latest") for line in ollama_lines[1:] if line.split()]
    discovered = {
        "codex": codex_models,
        "claude": [row["id"] for row in MODEL_CATALOG["claude"]],
        "gemini": agy_models,
        "ollama-gemma4": ollama_models,
        "ollama-twinkle": ollama_models,
    }
    current = {
        "codex": codex_current,
        "claude": "CLI 自動選擇（未固定）",
        "gemini": "CLI 自動選擇（未固定）",
        "ollama-gemma4": "gemma4:12b-mlx",
        "ollama-twinkle": "TwinkleAI/gemma-3-4B-T1-it",
    }
    for provider, meta in PROVIDERS.items():
        cli = str(meta["cli"])
        path = _cli_path(cli)
        version = _run([path, "--version"], timeout=5).splitlines()[-1] if path else ""
        available = list(dict.fromkeys([*discovered.get(provider, []), *[row["id"] for row in MODEL_CATALOG.get(provider, [])]]))
        result[provider] = {
            "installed": bool(path), "path": path or "", "version": version,
            "cli_default": current.get(provider, ""), "models": available,
        }
    _DISCOVERY_CACHE = (time.monotonic(), copy.deepcopy(result))
    return result
