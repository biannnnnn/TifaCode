"""sideQuery 语义召回：基于关键词的轻量级上下文检索。
不依赖外部 embedding 模型，使用 TF-IDF 风格的关键词权重匹配。"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from tifacode.agent.messages import Conversation

logger = logging.getLogger(__name__)

# 中英文分词：英文按空白+标点，中文按单字+常用词
_WORD_RE = re.compile(r"[a-zA-Z_]\w+|[^\W_]", re.UNICODE)
_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "about", "also", "this", "that",
    "and", "but", "or", "if", "while", "it", "its", "he", "she", "they",
    "them", "we", "you", "me", "us", "my", "your", "our", "their",
}


def _tokenize(text: str) -> list[str]:
    words = _WORD_RE.findall(text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


def _extract_keywords(text: str, top_n: int = 10) -> list[tuple[str, int]]:
    tokens = _tokenize(text)
    counter = Counter(tokens)
    return counter.most_common(top_n)


class SemanticIndex:
    """轻量级语义索引：存储对话块的关键词，支持相似度检索。"""

    def __init__(self) -> None:
        self._chunks: list[dict[str, Any]] = []

    def index_conversation(self, conversation: Conversation) -> int:
        """从 Conversation 中提取并索引所有 user/assistant 消息。"""
        indexed = 0
        for i, m in enumerate(conversation._messages):
            if m["role"] in ("system", "tool"):
                continue
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") in ("text",)
                )
            if not content or len(str(content)) < 20:
                continue

            keywords = _extract_keywords(str(content))
            if not keywords:
                continue

            self._chunks.append({
                "msg_index": i,
                "role": m["role"],
                "content_preview": str(content)[:300],
                "keywords": keywords,
            })
            indexed += 1
        logger.info("语义索引: indexed=%d chunks", indexed)
        return indexed

    def query(self, current_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """给定当前文本，返回最相关的前 top_k 个对话片段。"""
        query_kw = dict(_extract_keywords(current_text, top_n=20))
        if not query_kw:
            return []

        scored = []
        for chunk in self._chunks:
            score = 0
            # 计算 TF 乘积作为相关性得分
            for kw, weight in chunk["keywords"]:
                if kw in query_kw:
                    score += weight * query_kw[kw]
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:top_k]]

    def clear(self) -> None:
        self._chunks.clear()


_semantic_index: SemanticIndex | None = None


def get_semantic_index() -> SemanticIndex:
    global _semantic_index
    if _semantic_index is None:
        _semantic_index = SemanticIndex()
    return _semantic_index


def recall_relevant_context(conversation: Conversation, current_query: str, top_k: int = 3) -> str:
    """sideQuery 入口：检索与当前查询相关的历史上下文片段。
    返回格式化的上下文文本，可注入到 system prompt。"""
    index = get_semantic_index()
    results = index.query(current_query, top_k=top_k)
    if not results:
        return ""

    lines = ["## 相关历史上下文 (语义召回)", ""]
    for r in results:
        lines.append(f"- [{r['role']}] {r['content_preview']}")
    return "\n".join(lines)
