#!/usr/bin/env python3
"""跨程序、可重入的閱讀資料庫寫入鎖。

local-web 是多執行緒服務，AI 補摘要等工作則是另外啟動的 Python 程序；只用
threading.RLock 無法阻止兩邊同時做「讀取 -> 修改 -> 整檔覆寫」。所有會改寫
閱讀資料庫的交易應共用這把 flock，並只在最後重新讀取、合併與寫回時持有。
"""
from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
DATABASE_WRITE_LOCK_PATH = ROOT / ".cache" / "database-write.lock"

_THREAD_LOCK = threading.RLock()
_LOCAL = threading.local()


@contextmanager
def database_write_lock(lock_path: Path = DATABASE_WRITE_LOCK_PATH) -> Iterator[None]:
    """序列化跨執行緒、跨程序的資料庫讀改寫交易。

    同一執行緒可重入，讓上層交易與底層 write_jsonl 都能保守地要求鎖，而不會
    自己鎖死。不同程序會在同一個 lock file 上等待 flock。
    """
    with _THREAD_LOCK:
        depth = int(getattr(_LOCAL, "depth", 0))
        if depth:
            _LOCAL.depth = depth + 1
            try:
                yield
            finally:
                _LOCAL.depth -= 1
            return

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            _LOCAL.depth = 1
            _LOCAL.handle = handle
            yield
        finally:
            _LOCAL.depth = 0
            _LOCAL.handle = None
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
