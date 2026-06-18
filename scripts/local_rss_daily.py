#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"
REPORT = ROOT / ".cache" / "rss-fetch-report.md"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def notify(title: str, message: str) -> None:
    command = [
        "osascript",
        "-e",
        f'display notification "{message}" with title "{title}"',
    ]
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass


def main() -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "fetch_rss.py"),
        "--candidate-output",
        str(CANDIDATES),
        "--dismissed",
        str(DISMISSED),
        "--report",
        str(REPORT),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True)
    candidates = load_jsonl(CANDIDATES)
    keep_count = sum(1 for item in candidates if (item.get("triage") or {}).get("recommendation") == "suggest-keep")
    skip_count = sum(1 for item in candidates if (item.get("triage") or {}).get("recommendation") == "suggest-skip")
    message = f"候選 {len(candidates)} 筆；建議收 {keep_count}，建議不要看 {skip_count}。請打開本機網頁候選清單。"
    print(message)
    notify("Ian Open News RSS 已抓完", message)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
