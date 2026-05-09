from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, output: str = "", **metadata: Any) -> "ToolResult":
        return cls(success=True, output=output, metadata=metadata)

    @classmethod
    def fail(
        cls,
        error: str,
        output: str = "",
        error_code: str = "tool_error",
        **metadata: Any,
    ) -> "ToolResult":
        return cls(success=False, output=output, error=error, error_code=error_code, metadata=metadata)

    def to_text(self, limit: int | None = None) -> str:
        body = self.output if self.success else self.error
        if not body:
            body = "(无输出)" if self.success else "工具执行失败"
        if self.output and self.error and not self.success:
            body = f"{self.error}\n\n{self.output}"
        if limit and limit > 0 and len(body) > limit:
            original_length = len(body)
            self.metadata.update({
                "truncated": True,
                "original_length": original_length,
                "output_limit": limit,
            })
            notice = f"\n\n[输出已截断：原始长度 {original_length} 字符，限制 {limit} 字符]\n\n"
            if limit <= len(notice) + 20:
                body = body[:limit]
                self.metadata["rendered_length"] = len(body)
                return body
            keep = max(1, (limit - len(notice)) // 2)
            body = (
                f"{body[:keep]}\n\n"
                f"[输出已截断：原始长度 {original_length} 字符，限制 {limit} 字符]\n\n"
                f"{body[-keep:]}"
            )
            self.metadata["rendered_length"] = len(body)
        else:
            self.metadata.setdefault("truncated", False)
            self.metadata["original_length"] = len(body)
            self.metadata["rendered_length"] = len(body)
        return body


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]
    required_parameters: list[str] | None = None

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        ...

    def to_schema(self) -> dict[str, Any]:
        required = self.required_parameters
        if required is None:
            required = list(self.parameters.keys())
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": required,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._tiers: dict[str, int] = {}  # name -> tier
        self._active_tier: int = 1

    def register(self, tool: Tool, tier: int = 1) -> None:
        self._tools[tool.name] = tool
        self._tiers[tool.name] = tier

    def set_active_tier(self, tier: int) -> None:
        self._active_tier = tier

    @property
    def active_tier(self) -> int:
        return self._active_tier

    def get_schemas(self, tier: int | None = None) -> list[dict[str, Any]]:
        t = tier if tier is not None else self._active_tier
        return [
            tool.to_schema()
            for name, tool in self._tools.items()
            if self._tiers.get(name, 1) <= t
        ]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.fail(f"未知工具 '{name}'", error_code="unknown_tool")
        try:
            return await tool.execute(**params)
        except Exception as e:
            return ToolResult.fail(f"工具执行出错：{e}", error_code="tool_exception", exception_type=type(e).__name__)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
