from __future__ import annotations

import logging

from tifacode.agent.messages import Conversation
from tifacode.config.settings import Settings

logger = logging.getLogger(__name__)


def compact_conversation(conversation: Conversation, settings: Settings) -> int:
    """如果对话超过 token 阈值，压缩旧消息。返回被修剪的消息数。"""
    if not settings.compact_enabled:
        return 0

    tokens = conversation.estimate_tokens()
    if tokens <= settings.compact_token_threshold:
        return 0

    logger.info(
        "触发上下文压缩: estimated_tokens=%d threshold=%d",
        tokens,
        settings.compact_token_threshold,
    )

    trimmed = conversation.trim_old_tool_results(
        keep_recent=settings.compact_keep_recent_turns * 2,
        snip_limit=settings.tool_result_snip_limit,
    )

    logger.info("上下文压缩完成: trimmed=%d messages", trimmed)
    return trimmed
