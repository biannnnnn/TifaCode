from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tifacode.agent.messages import Conversation
from tifacode.config.settings import SESSION_DIR


class SessionStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = base_dir or SESSION_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = name.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe}.json"

    def save(self, name: str, conversation: Conversation) -> None:
        data = {
            "session_name": name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "conversation": conversation.to_dict(),
        }
        self._path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, name: str) -> Conversation:
        path = self._path(name)
        if not path.exists():
            return Conversation()
        data = json.loads(path.read_text(encoding="utf-8"))
        return Conversation.from_dict(data.get("conversation", {}))

    def list_sessions(self) -> list[str]:
        sessions = []
        for f in sorted(self._dir.glob("*.json")):
            name = f.stem
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                updated = data.get("updated_at", "?")
                sessions.append(f"{name} ({updated})")
            except Exception:
                sessions.append(name)
        return sessions
