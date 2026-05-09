from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


class FileTracker:
    """追踪 ReadTool 读取过的文件及其 mtime，供 Edit/Write 校验。"""

    def __init__(self) -> None:
        self._records: dict[str, float] = {}  # file_path -> mtime

    def record_read(self, file_path: str) -> float:
        try:
            mtime = os.path.getmtime(file_path)
        except OSError:
            mtime = 0.0
        self._records[file_path] = mtime
        return mtime

    def check_stale(self, file_path: str) -> tuple[bool, float, float]:
        """返回 (is_stale, last_read_mtime, current_mtime)。
        若文件未被读取过，is_stale 为 False。"""
        if file_path not in self._records:
            return False, 0.0, 0.0
        last_mtime = self._records[file_path]
        try:
            current_mtime = os.path.getmtime(file_path)
        except OSError:
            current_mtime = 0.0
        return current_mtime != last_mtime, last_mtime, current_mtime

    def invalidate(self, file_path: str) -> None:
        self._records.pop(file_path, None)

    def clear(self) -> None:
        self._records.clear()


_file_tracker: FileTracker | None = None


def get_file_tracker() -> FileTracker:
    global _file_tracker
    if _file_tracker is None:
        _file_tracker = FileTracker()
    return _file_tracker
