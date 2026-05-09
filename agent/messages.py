from __future__ import annotations

import json
from typing import Any


class Conversation:
    def __init__(self, system_prompt: str = "") -> None:
        self._messages: list[dict[str, Any]] = []
        if system_prompt:
            self._messages.append({"role": "system", "content": system_prompt})

    def add_user(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def add_assistant(self, content: list[dict[str, Any]]) -> None:
        """content: [{"type":"text","text":"..."}, {"type":"tool_use","id":"...","name":"...","input":{...}}]"""
        self._messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_use_id: str, result: str) -> None:
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_use_id,
            "content": result,
        })

    def to_api_format(self, provider: str) -> list[dict[str, Any]]:
        if provider == "anthropic":
            return self._to_anthropic()
        elif provider in ("openai", "deepseek"):
            return self._to_openai()
        else:
            return list(self._messages)

    def _to_openai(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for m in self._messages:
            if m["role"] == "assistant":
                entry: dict[str, Any] = {"role": "assistant"}
                content = m.get("content", m.get("text", ""))
                if isinstance(content, list):
                    texts: list[str] = []
                    tool_calls: list[dict[str, Any]] = []
                    for block in content:
                        if block["type"] == "text":
                            texts.append(block["text"])
                        elif block["type"] == "reasoning":
                            entry["reasoning_content"] = block["text"]
                        elif block["type"] == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"], ensure_ascii=False),
                                },
                            })
                    entry["content"] = "\n".join(texts) if texts else None
                    if tool_calls:
                        entry["tool_calls"] = tool_calls
                else:
                    entry["content"] = content
                result.append(entry)
            else:
                result.append(dict(m))
        return result

    def _to_anthropic(self) -> list[dict[str, Any]]:
        """将内部格式转为 Anthropic API 格式。
        内部使用 OpenAI-like 格式存储，转 Anthropic 时需要：
        - system 不出现为消息 role
        - tool role 转为 user role 包裹 tool_result
        """
        result: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        for m in self._messages:
            if m["role"] == "system":
                continue  # 在 backend 中单独提取
            elif m["role"] == "tool":
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                })
            else:
                if pending_tool_results:
                    result.append({"role": "user", "content": pending_tool_results})
                    pending_tool_results = []
                if m["role"] == "user":
                    result.append({"role": "user", "content": m["content"]})
                elif m["role"] == "assistant":
                    result.append({"role": "assistant", "content": m["content"]})

        if pending_tool_results:
            result.append({"role": "user", "content": pending_tool_results})

        return result

    def to_dict(self) -> dict[str, Any]:
        return {"messages": self._messages}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        conv = cls()
        conv._messages = data.get("messages", [])
        return conv

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    @property
    def last_assistant_content(self) -> list[dict[str, Any]]:
        for m in reversed(self._messages):
            if m["role"] == "assistant":
                return m.get("content", [])
        return []

    def get_system_prompt(self) -> str:
        parts = [m["content"] for m in self._messages if m["role"] == "system"]
        return "\n".join(parts)

    def estimate_tokens(self) -> int:
        total = 0
        for m in self._messages:
            content = m.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block)) // 3
                    else:
                        total += len(str(block)) // 3
            else:
                total += len(str(content)) // 3
        return total

    def trim_old_tool_results(self, keep_recent: int = 20, snip_limit: int = 4000) -> int:
        """将旧的 tool_result 替换为摘要，保留最近 N 条完整结果。返回被修剪的消息数。"""
        tool_indices = [i for i, m in enumerate(self._messages) if m["role"] == "tool"]
        if len(tool_indices) <= keep_recent:
            return 0

        trimmed = 0
        for idx in tool_indices[:-keep_recent]:
            content = self._messages[idx].get("content", "")
            if len(content) > snip_limit:
                head = content[:snip_limit // 2]
                tail = content[-(snip_limit // 2):]
                self._messages[idx]["content"] = head + "\n...[truncated]...\n" + tail
            trimmed += 1
        return trimmed
