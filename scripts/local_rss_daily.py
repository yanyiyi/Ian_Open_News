#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / ".cache" / "rss-candidates.jsonl"
DISMISSED = ROOT / ".cache" / "rss-dismissed.jsonl"
REPORT = ROOT / ".cache" / "rss-fetch-report.md"
STATUS = ROOT / ".cache" / "rss-fetch-status.json"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def write_status(payload: dict) -> None:
    from datetime import datetime, timezone

    STATUS.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if STATUS.exists():
        try:
            current = json.loads(STATUS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
    current.update(payload)
    current["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    STATUS.write_text(json.dumps(current, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


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

    codex_message = ""
    if os.environ.get("IAN_OPEN_NEWS_AUTO_CODEX", "1") != "0":
        write_status({"phase": "codex", "message": "RSS 已抓完，正在補 Codex 閱讀建議與摘要。"})
        codex_command = [
            sys.executable,
            str(ROOT / "scripts" / "codex_enrich_reviews.py"),
            "--target",
            "candidates",
            "--limit",
            "24",
            "--batch-size",
            "6",
        ]
        try:
            codex_result = subprocess.run(
                codex_command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=1800,
            )
            if codex_result.returncode == 0:
                codex_message = "Codex 建議與摘要已補上。"
                write_status({"phase": "finished", "message": "RSS 抓取與 Codex 補寫完成。"})
            else:
                codex_message = "Codex 補寫失敗，請打開本機網頁手動按鈕補跑。"
                write_status({"phase": "finished-with-errors", "message": codex_message})
                print(codex_result.stdout)
                print(codex_result.stderr, file=sys.stderr)
        except (OSError, subprocess.TimeoutExpired) as exc:
            codex_message = "Codex 補寫逾時或無法啟動，請打開本機網頁手動補跑。"
            write_status({"phase": "finished-with-errors", "message": codex_message})
            print(f"Codex enrichment failed: {exc}", file=sys.stderr)
    else:
        codex_message = "已略過 Codex 自動補寫。"
        write_status({"phase": "finished", "message": "RSS 抓取完成，已略過 Codex 自動補寫。"})

    candidates = load_jsonl(CANDIDATES)
    keep_count = sum(1 for item in candidates if (item.get("triage") or {}).get("recommendation") == "suggest-keep")
    skip_count = sum(1 for item in candidates if (item.get("triage") or {}).get("recommendation") == "suggest-skip")
    message = f"候選 {len(candidates)} 筆；建議收 {keep_count}，建議不要看 {skip_count}。{codex_message}"
    print(message)
    notify("Ian Open News RSS 已抓完", message)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
