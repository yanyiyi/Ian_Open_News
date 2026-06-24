#!/usr/bin/env python3
"""回歸測試：資料庫寫入鎖防止並發 lost-update。

重現孤兒 review-event 的根因——ThreadingHTTPServer 並發處理「讀取→修改→整檔覆寫」時，
某執行緒的舊快照會覆寫掉別人剛寫入的資料。本測試以真正被 @with_db_write_lock 裝飾的
Handler.pop_candidate 高度並發執行，驗證上鎖後零 lost-update；並對照未裝飾版（__wrapped__）
證明若沒有鎖確實會掉資料。

執行：python3 scripts/test_db_write_lock.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import local_web as lw  # noqa: E402


def _setup(path: Path, n: int) -> None:
    lw.write_jsonl(path, [{"id": f"cand-{i}", "title": f"t{i}", "url": f"https://example/{i}"} for i in range(n)])


def _run(n: int, locked: bool) -> tuple[int, int]:
    """每個執行緒 pop 一個不同的候選，回傳 (成功 pop 數, 殘留數)。理想 = (n, 0)。"""
    tmp = Path(tempfile.mkdtemp()) / "cand.jsonl"
    original = lw.CANDIDATES
    lw.CANDIDATES = tmp
    try:
        _setup(tmp, n)
        handler = lw.Handler.__new__(lw.Handler)
        pop = handler.pop_candidate if locked else (lambda cid: lw.Handler.pop_candidate.__wrapped__(handler, cid))
        barrier = threading.Barrier(n)
        results: list[object] = []
        guard = threading.Lock()

        def worker(i: int) -> None:
            barrier.wait()  # 同時起跑，放大競爭
            popped = pop(f"cand-{i}")
            with guard:
                results.append(popped)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        remaining = lw.load_jsonl(tmp)
        return sum(1 for r in results if r), len(remaining)
    finally:
        lw.CANDIDATES = original


def main() -> int:
    n = 50
    locked_ok, locked_remaining = _run(n, locked=True)
    print(f"[locked]   pop 成功 {locked_ok}/{n}，殘留 {locked_remaining}（理想 0）")

    # 對照組：未裝飾版本，重跑幾次看是否掉資料（並發競爭本質上有隨機性）。
    worst_remaining = 0
    for _ in range(5):
        _ok, remaining = _run(n, locked=False)
        worst_remaining = max(worst_remaining, remaining)
    print(f"[unlocked] 5 次中最嚴重殘留 {worst_remaining}（>0 代表沒有鎖時會 lost-update）")

    if locked_remaining != 0 or locked_ok != n:
        print("FAIL：上鎖後仍有 lost-update。")
        return 1
    print("PASS：上鎖後零 lost-update。")
    if worst_remaining == 0:
        print("注意：這次未裝飾版剛好沒重現競爭（時序問題），但上鎖版已驗證正確。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
