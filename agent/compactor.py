"""4 层上下文压缩流水线：
  Stage 1 — budget_truncation: 单条工具结果超限截断
  Stage 2 — stale_snip:      旧工具结果替换为一行摘要
  Stage 3 — microcompact:    50-70% 利用率时合并同轮工具结果、删除早期推理
  Stage 4 — auto_compact:    >85% 利用率时生成结构化摘要，仅保留最近 N 轮
"""
from __future__ import annotations

import logging
from typing import Any

from tifacode.agent.messages import Conversation
from tifacode.config.settings import Settings

logger = logging.getLogger(__name__)

# 模型上下文窗口 (tokens)
MODEL_CONTEXT_WINDOWS = {
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4-7": 200_000,
    "claude-haiku-4-5": 200_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "deepseek-v4-pro": 128_000,
}


def _get_context_window(settings: Settings) -> int:
    if settings.compact_context_window > 0:
        return settings.compact_context_window
    return MODEL_CONTEXT_WINDOWS.get(settings.model, 128_000)


def _utilization(conversation: Conversation, context_window: int) -> float:
    return conversation.estimate_tokens() / context_window


# ════════════════════════════════════════════════════════
# Stage 1: budget_truncation
# ════════════════════════════════════════════════════════

def stage_budget_truncation(conversation: Conversation, settings: Settings) -> int:
    """对每条 tool_result 做长度上限截断。"""
    limit = settings.tool_result_budget_limit
    if limit <= 0:
        return 0
    trimmed = 0
    for i, m in enumerate(conversation._messages):
        if m["role"] == "tool" and len(str(m.get("content", ""))) > limit:
            head = str(m["content"])[:limit // 2]
            tail = str(m["content"])[-(limit // 2):]
            m["content"] = f"{head}\n...[budget truncation]...\n{tail}"
            trimmed += 1
    if trimmed:
        logger.info("Stage 1 budget_truncation: trimmed=%d messages", trimmed)
    return trimmed


# ════════════════════════════════════════════════════════
# Stage 2: stale_snip
# ════════════════════════════════════════════════════════

def stage_stale_snip(conversation: Conversation, settings: Settings) -> int:
    """将旧工具结果替换为单行摘要。保留最近 N 轮完整内容。"""
    keep = settings.compact_keep_recent_turns

    # 从后往前数轮次（user message = 一轮）
    turn_numbers: dict[int, int] = {}  # msg_index -> turn_number
    t = 0
    for i, m in enumerate(conversation._messages):
        if m["role"] == "user":
            t += 1
        turn_numbers[i] = max(1, t)

    total_turns = t
    cutoff = total_turns - keep + 1
    if cutoff <= 1:
        return 0

    snipped = 0
    snip_limit = settings.tool_result_snip_limit
    for i, m in enumerate(conversation._messages):
        if m["role"] == "tool" and turn_numbers[i] < cutoff:
            content = str(m.get("content", ""))
            if len(content) > snip_limit:
                short = content[:snip_limit // 2] + "\n...[stale snip]...\n" + content[-(snip_limit // 2):]
                m["content"] = short
                snipped += 1

    if snipped:
        logger.info("Stage 2 stale_snip: snipped=%d, cutoff_turn=%d", snipped, cutoff)
    return snipped


# ════════════════════════════════════════════════════════
# Stage 3: microcompact
# ════════════════════════════════════════════════════════

def stage_microcompact(conversation: Conversation, settings: Settings) -> int:
    """在 50-70% 利用率时：合并同轮工具结果、删除早期 reasoning、整理冗余。"""
    compacted = 0

    # 1. 删除前半部分的 reasoning 内容（早期推理对后续价值低）
    messages = conversation._messages
    total = len(messages)
    scan_end = max(3, total // 2)
    for i in range(min(scan_end, total)):
        if messages[i]["role"] == "assistant":
            content = messages[i].get("content")
            if isinstance(content, list):
                new_content = [b for b in content if b.get("type") != "reasoning"]
                if len(new_content) < len(content):
                    messages[i]["content"] = new_content
                    compacted += 1

    # 2. 合并同轮内连续 tool_result 为一条摘要
    i = 0
    while i < len(messages) - 1:
        if messages[i]["role"] == "tool" and messages[i + 1]["role"] == "tool":
            c1 = str(messages[i].get("content", ""))
            c2 = str(messages[i + 1].get("content", ""))
            # 合并：摘要格式
            merged = (
                f"[合并工具结果: {len(c1)} + {len(c2)} chars]\n"
                f"Result 1: {c1[:200]}...\n"
                f"Result 2: {c2[:200]}..."
            )
            messages[i]["content"] = merged
            messages.pop(i + 1)
            compacted += 1
        else:
            i += 1

    if compacted:
        logger.info("Stage 3 microcompact: compacted=%d", compacted)
    return compacted


# ════════════════════════════════════════════════════════
# Stage 4: auto_compact
# ════════════════════════════════════════════════════════

def _build_conversation_summary(messages: list[dict[str, Any]], max_chars: int = 3000) -> str:
    """从旧消息中提取结构化摘要：任务目标、已改文件、关键决策。"""
    user_requests: list[str] = []
    files_modified: set[str] = set()
    tools_used: list[str] = []
    errors: list[str] = []

    for m in messages:
        if m["role"] == "user":
            text = m.get("content", "")
            if isinstance(text, str) and len(text) > 10:
                user_requests.append(text[:300])

        elif m["role"] == "tool":
            content = str(m.get("content", ""))
            # 提取文件路径
            import re
            for path in re.findall(r"file_path[=:]\s*['\"]?([^'\"\s,}]+)", content):
                files_modified.add(path)
            if "error" in content.lower() or "fail" in content.lower():
                errors.append(content[:200])

        elif m["role"] == "assistant":
            content = m.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_use":
                        tools_used.append(block.get("name", ""))

    lines = ["## 对话摘要", ""]

    if user_requests:
        lines.append("### 用户请求")
        for r in user_requests[-5:]:  # 最近5条
            lines.append(f"- {r}")
        lines.append("")

    if files_modified:
        lines.append("### 涉及文件")
        for f in sorted(files_modified)[:15]:
            lines.append(f"- `{f}`")
        lines.append("")

    if tools_used:
        from collections import Counter
        tool_counts = Counter(tools_used).most_common(10)
        lines.append("### 工具使用")
        lines.append(", ".join(f"{n}×{c}" for n, c in tool_counts))
        lines.append("")

    if errors:
        lines.append("### 曾遇到错误")
        for e in errors[-3:]:
            lines.append(f"- {e}")
        lines.append("")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 50] + "\n...(摘要已截断)"
    return result


def stage_auto_compact(conversation: Conversation, settings: Settings) -> int:
    """>85% 利用率：生成结构化摘要替换旧消息，仅保留最近 N 轮完整。"""
    keep = settings.compact_keep_recent_turns
    messages = conversation._messages

    # 从后往前找最近 N 轮
    turn_count = 0
    split_idx = 0  # 0 表示未找到切分点
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] == "user":
            turn_count += 1
            if turn_count >= keep:
                split_idx = i
                break

    if split_idx <= 1 or turn_count < keep:
        return 0

    old = messages[:split_idx]
    recent = messages[split_idx:]

    summary_text = _build_conversation_summary(old)

    # 构建新的消息列表：system + 摘要 user + 摘要 assistant + recent
    new_messages: list[dict[str, Any]] = []
    for m in old:
        if m["role"] == "system":
            new_messages.append(m)
            break

    new_messages.append({"role": "user", "content": summary_text})
    new_messages.append({"role": "assistant", "content": [{"type": "text", "text": "已理解。之前的对话上下文已压缩为摘要，我将基于摘要继续。"}]})
    new_messages.extend(recent)

    old_count = len(conversation._messages)
    conversation._messages = new_messages
    removed = old_count - len(new_messages)

    logger.info("Stage 4 auto_compact: removed=%d messages, kept=%d", removed, len(recent))
    return removed


# ════════════════════════════════════════════════════════
# 流水线编排
# ════════════════════════════════════════════════════════

def compact_conversation(conversation: Conversation, settings: Settings) -> dict[str, int]:
    """按利用率执行对应压缩阶段。返回各阶段执行计数。"""
    if not settings.compact_enabled:
        return {"budget": 0, "stale": 0, "micro": 0, "auto": 0}

    ctx_window = _get_context_window(settings)
    util = _utilization(conversation, ctx_window)
    tokens = conversation.estimate_tokens()

    result = {"budget": 0, "stale": 0, "micro": 0, "auto": 0}

    # Stage 1: 每条消息都做 budget 检查（仅在添加消息时隐式完成，这里做二次检查）
    result["budget"] = stage_budget_truncation(conversation, settings)

    # Stage 2: 始终检查 stale
    result["stale"] = stage_stale_snip(conversation, settings)
    util = _utilization(conversation, ctx_window)

    # Stage 3: 50-70% → microcompact
    if util >= settings.compact_micro_threshold:
        result["micro"] = stage_microcompact(conversation, settings)

    # Stage 4: >85% → auto_compact
    util = _utilization(conversation, ctx_window)
    if util >= settings.compact_auto_threshold:
        result["auto"] = stage_auto_compact(conversation, settings)

    if any(result.values()):
        new_tokens = conversation.estimate_tokens()
        logger.info(
            "压缩完成: stages=%s, tokens %d→%d (saved %d), util %.0f%%→%.0f%%",
            [k for k, v in result.items() if v],
            tokens,
            new_tokens,
            tokens - new_tokens,
            util * 100,
            _utilization(conversation, ctx_window) * 100,
        )

    return result
