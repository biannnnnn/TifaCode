from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Union

from tifacode.config.settings import Settings


@dataclass
class TextDelta:
    text: str


@dataclass
class ReasoningDelta:
    text: str


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class Done:
    stop_reason: str
    usage: dict[str, int]


Event = Union[TextDelta, ReasoningDelta, ToolUse, Done]


class BackendAdapter(ABC):
    @abstractmethod
    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[Event]:
        ...


class AnthropicBackend(BackendAdapter):
    def __init__(self, settings: Settings) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model
        self._max_turns = settings.max_turns

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[Event]:
        import anthropic.types as at

        system = ""
        api_messages: list[dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                api_messages.append(m)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 8192,
            "messages": api_messages,
        }
        if system.strip():
            kwargs["system"] = system.strip()
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    cb = event.content_block
                    if cb.type == "tool_use":
                        yield ToolUse(id=cb.id, name=cb.name, input={})
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield TextDelta(text=delta.text)
                    elif delta.type == "input_json_delta":
                        pass  # 累积到 message_stop 时统一处理
                elif event.type == "message_stop":
                    msg: at.Message = stream.current_message_snapshot
                    for block in msg.content:
                        if block.type == "tool_use":
                            yield ToolUse(id=block.id, name=block.name, input=block.input or {})
                    usage = {
                        "input_tokens": getattr(msg.usage, "input_tokens", 0),
                        "output_tokens": getattr(msg.usage, "output_tokens", 0),
                    }
                    yield Done(stop_reason=msg.stop_reason or "end_turn", usage=usage)


class OpenAIBackend(BackendAdapter):
    def __init__(self, settings: Settings) -> None:
        import openai

        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.model
        self._max_turns = settings.max_turns

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[Event]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self._client.chat.completions.create(**kwargs)

        collected_tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        usage = {}

        async for chunk in response:
            if chunk.usage:
                usage = {
                    "input_tokens": chunk.usage.prompt_tokens or 0,
                    "output_tokens": chunk.usage.completion_tokens or 0,
                }
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue
            finish_reason = chunk.choices[0].finish_reason or finish_reason

            if delta.content:
                yield TextDelta(text=delta.content)

            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                yield ReasoningDelta(text=delta.reasoning_content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {"id": tc.id or "", "name": "", "arguments": ""}
                    if tc.id:
                        collected_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            collected_tool_calls[idx]["name"] += tc.function.name
                        if tc.function.arguments:
                            collected_tool_calls[idx]["arguments"] += tc.function.arguments

            if finish_reason and finish_reason != "stop":
                # 可能是 tool_calls 或 stop
                pass

        for tc in collected_tool_calls.values():
            import json
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                args = {}
            yield ToolUse(id=tc["id"], name=tc["name"], input=args)

        yield Done(stop_reason=finish_reason or "stop", usage=usage)


class DeepSeekBackend(OpenAIBackend):
    def __init__(self, settings: Settings) -> None:
        import openai

        self._client = openai.AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
        self._model = settings.model
        self._max_turns = settings.max_turns


def create_backend(settings: Settings) -> BackendAdapter:
    provider = settings.provider

    key_env_map = {
        "anthropic": ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
        "openai": ("OPENAI_API_KEY", settings.openai_api_key),
        "deepseek": ("DEEPSEEK_API_KEY", settings.deepseek_api_key),
    }
    env_var, api_key = key_env_map.get(provider, ("", ""))
    if not api_key:
        raise ValueError(
            f"未设置 {provider} 的 API Key。请设置环境变量 {env_var}，\n"
            f"或在 ~/.tifacode/config.yaml 中配置 api_key 字段"
        )

    if provider == "anthropic":
        return AnthropicBackend(settings)
    elif provider == "openai":
        return OpenAIBackend(settings)
    elif provider == "deepseek":
        return DeepSeekBackend(settings)
    else:
        raise ValueError(f"不支持的 provider: {settings.provider}")
