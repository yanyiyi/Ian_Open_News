#!/usr/bin/env python3
from __future__ import annotations

import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database_write_lock import database_write_lock


def hold_lock(path: str, ready: object, release: object) -> None:
    with database_write_lock(Path(path)):
        ready.set()
        release.wait(5)


def enter_lock(path: str, entered: object) -> None:
    with database_write_lock(Path(path)):
        entered.set()


class DatabaseWriteLockTest(unittest.TestCase):
    def test_separate_process_waits_for_lock_holder(self) -> None:
        context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = str(Path(tmp) / "database-write.lock")
            ready = context.Event()
            release = context.Event()
            entered = context.Event()
            holder = context.Process(target=hold_lock, args=(lock_path, ready, release))
            waiter = context.Process(target=enter_lock, args=(lock_path, entered))
            holder.start()
            self.assertTrue(ready.wait(3), "第一個程序沒有取得測試鎖")
            waiter.start()
            self.assertFalse(entered.wait(0.2), "第二個程序不應穿過仍被持有的 flock")
            release.set()
            self.assertTrue(entered.wait(3), "釋放後第二個程序應能取得 flock")
            holder.join(3)
            waiter.join(3)
            self.assertEqual(holder.exitcode, 0)
            self.assertEqual(waiter.exitcode, 0)


if __name__ == "__main__":
    unittest.main()
