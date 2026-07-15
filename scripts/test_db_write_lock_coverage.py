#!/usr/bin/env python3
"""AST 防呆：local_web.py 凡是「load_jsonl → write_jsonl 整檔覆寫」的讀改寫函式，
必須套 @with_db_write_lock。ThreadingHTTPServer 並發下漏鎖會 lost-update：
item 被舊快照覆寫掉、review-event 因 append 倖存，留下孤兒事件（2026-07-15 實際發生過）。"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

LOCAL_WEB = Path(__file__).resolve().parent / "local_web.py"

# 讀改寫的起點（載入整份 JSONL 當快照）
LOAD_CALLS = {"load_jsonl"}
# 會整檔覆寫（或內含讀改寫）的呼叫；upsert_jsonl / remove_jsonl_ids 自身已上鎖，
# 但呼叫端若先 load 再依快照決定寫什麼，仍構成跨呼叫的讀改寫視窗。
WRITE_CALLS = {"write_jsonl", "upsert_jsonl", "remove_jsonl_ids"}
LOCK_DECORATOR = "with_db_write_lock"

# 明確豁免：函式本體同時 load+write，但所有呼叫端都已在鎖內（豁免前先查證呼叫鏈）。
ALLOWLIST: set[str] = set()


def call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def has_lock_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == LOCK_DECORATOR:
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr == LOCK_DECORATOR:
            return True
    return False


def read_modify_write_functions() -> list[tuple[str, int, bool]]:
    tree = ast.parse(LOCAL_WEB.read_text(encoding="utf-8"))
    found: list[tuple[str, int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == LOCK_DECORATOR:
            continue
        names = call_names(node)
        if names & LOAD_CALLS and names & WRITE_CALLS:
            found.append((node.name, node.lineno, has_lock_decorator(node)))
    return found


class DbWriteLockCoverageTest(unittest.TestCase):
    def test_read_modify_write_functions_hold_db_write_lock(self) -> None:
        functions = read_modify_write_functions()
        self.assertTrue(functions, "AST 掃描異常：local_web.py 找不到任何讀改寫函式")

        missing = [
            f"{name}（local_web.py:{lineno}）"
            for name, lineno, locked in functions
            if not locked and name not in ALLOWLIST
        ]
        self.assertFalse(
            missing,
            "以下函式做「load_jsonl → 整檔覆寫」卻沒套 @with_db_write_lock，"
            "並發下會把別的執行緒剛寫入的紀錄抹掉（孤兒事件根因）：\n"
            + "\n".join(missing),
        )

    def test_allowlist_entries_still_exist(self) -> None:
        names = {name for name, _, _ in read_modify_write_functions()}
        stale = ALLOWLIST - names
        self.assertFalse(stale, f"豁免清單過期，函式已不存在或已無讀改寫：{sorted(stale)}")


if __name__ == "__main__":
    unittest.main()
