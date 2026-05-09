"""跨会话记忆：持久化关键决策、用户偏好、项目上下文到 ~/.tifacode/memory/。
新会话启动时自动加载相关记忆注入 system prompt。"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from tifacode.config.settings import CONFIG_DIR

logger = logging.getLogger(__name__)

MEMORY_DIR = CONFIG_DIR / "memory"
MEMORY_INDEX_FILE = MEMORY_DIR / "index.json"


def _ensure_dir() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


class MemoryEntry:
    def __init__(self, key: str, content: str, tags: list[str] | None = None,
                 ttl_seconds: int = 0) -> None:
        self.key = key
        self.content = content
        self.tags = tags or []
        self.content_hash = _content_hash(content)
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds  # 0 = 永不过期

    def is_expired(self) -> bool:
        if self.ttl_seconds <= 0:
            return False
        return time.time() - self.created_at > self.ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "tags": self.tags,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MemoryEntry:
        entry = cls(
            key=d["key"],
            content=d["content"],
            tags=d.get("tags", []),
            ttl_seconds=d.get("ttl_seconds", 0),
        )
        entry.content_hash = d.get("content_hash", _content_hash(d["content"]))
        entry.created_at = d.get("created_at", time.time())
        return entry


class MemoryStore:
    """文件持久化的跨会话记忆存储。"""

    def __init__(self) -> None:
        _ensure_dir()
        self._entries: dict[str, MemoryEntry] = {}
        self._load_index()

    def _load_index(self) -> None:
        if not MEMORY_INDEX_FILE.exists():
            return
        try:
            data = json.loads(MEMORY_INDEX_FILE.read_text(encoding="utf-8"))
            for item in data:
                entry = MemoryEntry.from_dict(item)
                if entry.is_expired():
                    self._delete_entry_file(entry)
                else:
                    self._entries[entry.key] = entry
        except Exception:
            logger.warning("加载记忆索引失败", exc_info=True)

    def _save_index(self) -> None:
        data = [e.to_dict() for e in self._entries.values() if not e.is_expired()]
        MEMORY_INDEX_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _entry_file(self, entry: MemoryEntry) -> Path:
        return MEMORY_DIR / f"{entry.content_hash}.json"

    def _delete_entry_file(self, entry: MemoryEntry) -> None:
        f = self._entry_file(entry)
        if f.exists():
            f.unlink()

    def put(self, key: str, content: str, tags: list[str] | None = None,
            ttl_seconds: int = 0) -> MemoryEntry:
        entry = MemoryEntry(key=key, content=content, tags=tags, ttl_seconds=ttl_seconds)
        self._entries[key] = entry
        self._entry_file(entry).write_text(
            json.dumps(entry.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._save_index()
        logger.info("记忆已保存: key=%s tags=%s", key, tags)
        return entry

    def get(self, key: str) -> MemoryEntry | None:
        entry = self._entries.get(key)
        if entry and entry.is_expired():
            self._delete_entry_file(entry)
            del self._entries[key]
            self._save_index()
            return None
        return entry

    def search(self, query_tags: list[str]) -> list[MemoryEntry]:
        results = []
        for entry in self._entries.values():
            if entry.is_expired():
                continue
            if any(tag.lower() in (t.lower() for t in entry.tags) for tag in query_tags):
                results.append(entry)
        return results

    def list_all(self) -> list[MemoryEntry]:
        return [e for e in self._entries.values() if not e.is_expired()]

    def delete(self, key: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry:
            self._delete_entry_file(entry)
            self._save_index()
            return True
        return False

    def clear(self) -> None:
        for entry in list(self._entries.values()):
            self._delete_entry_file(entry)
        self._entries.clear()
        self._save_index()

    def inject_into_prompt(self, tags: list[str] | None = None, max_entries: int = 5) -> str:
        """将相关记忆注入到提示词文本中。"""
        entries = self.search(tags) if tags else self.list_all()
        entries = entries[:max_entries]
        if not entries:
            return ""

        lines = ["## 跨会话记忆", ""]
        for e in entries:
            age = time.time() - e.created_at
            if age < 3600:
                ago = f"{int(age / 60)}分钟前"
            elif age < 86400:
                ago = f"{int(age / 3600)}小时前"
            else:
                ago = f"{int(age / 86400)}天前"
            lines.append(f"### {e.key} ({ago})")
            lines.append(e.content)
            lines.append("")
        return "\n".join(lines)


_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store
