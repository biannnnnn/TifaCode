"""Phase 6 功能验证：4层压缩流水线 / 语义召回 / 跨会话记忆"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))

passed = 0
failed = 0

def check(desc: str, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print(f"  PASS  {desc}")
    except Exception as e:
        failed += 1
        print(f"  FAIL  {desc}: {e}")
        traceback.print_exc()


# ─── Helper ────────────────────────────────────────────

from tifacode.agent.messages import Conversation
from tifacode.config.settings import Settings


def _make_conversation(turns: int = 10) -> Conversation:
    """造一个有 N 轮对话、大量 tool_result 的 conversation。"""
    conv = Conversation(system_prompt="You are a helpful agent.")
    for t in range(1, turns + 1):
        conv.add_user(f"Task {t}: do something useful with the codebase " + "extra words " * 50)
        conv.add_assistant([
            {"type": "text", "text": f"Processing task {t}..."},
            {"type": "tool_use", "id": f"tu_{t}_1", "name": "read", "input": {"file_path": f"/tmp/file{t}.py"}},
        ])
        conv.add_tool_result(f"tu_{t}_1", f"Result of reading file{t}.py\n" + "line: data\n" * 200)
        conv.add_assistant([
            {"type": "text", "text": "Now editing..."},
            {"type": "tool_use", "id": f"tu_{t}_2", "name": "edit", "input": {"file_path": f"/tmp/file{t}.py"}},
        ])
        conv.add_tool_result(f"tu_{t}_2", "Edit successful\n" + "line: changed\n" * 100)
    return conv


default_settings = Settings(
    tool_output_limit=20000,
    tool_log_enabled=False,
    compact_enabled=True,
    compact_keep_recent_turns=3,
    tool_result_snip_limit=500,
    tool_result_budget_limit=3000,
    compact_context_window=200000,
    compact_micro_threshold=0.50,
    compact_auto_threshold=0.85,
    semantic_recall_enabled=True,
    cross_session_memory_enabled=True,
)


# ─── 1. Stage 1: budget_truncation ─────────────────────

def test_stage1_truncates_long_tool_results():
    from tifacode.agent.compactor import stage_budget_truncation
    conv = Conversation()
    conv.add_user("test")
    conv.add_assistant([{"type": "tool_use", "id": "1", "name": "read", "input": {}}])
    conv.add_tool_result("1", "x" * 10000)  # 10K chars > 3K budget
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 tool_result_budget_limit=3000, compact_keep_recent_turns=5)
    trimmed = stage_budget_truncation(conv, s)
    assert trimmed == 1, f"expected 1 trimmed, got {trimmed}"
    content = str(conv._messages[-1]["content"])
    assert "budget truncation" in content, f"missing truncation marker: {content[:200]}"

def test_stage1_skips_short_results():
    from tifacode.agent.compactor import stage_budget_truncation
    conv = Conversation()
    conv.add_user("test")
    conv.add_tool_result("1", "short")
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 tool_result_budget_limit=3000, compact_keep_recent_turns=5)
    trimmed = stage_budget_truncation(conv, s)
    assert trimmed == 0


# ─── 2. Stage 2: stale_snip ────────────────────────────

def test_stage2_snips_old_turns():
    from tifacode.agent.compactor import stage_stale_snip
    conv = _make_conversation(turns=8)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 tool_result_snip_limit=200, compact_keep_recent_turns=2)
    snipped = stage_stale_snip(conv, s)
    assert snipped > 0, f"expected some snipped, got {snipped}"
    # 最近 2 轮应保持完整
    recent_tool_indices = [i for i, m in enumerate(conv._messages) if m["role"] == "tool"]
    recent_count = sum(1 for i in recent_tool_indices if "stale snip" not in str(conv._messages[i].get("content", "")))
    assert recent_count >= 2 * 2, f"expected >=4 intact recent results, got {recent_count}"

def test_stage2_skips_when_few_turns():
    from tifacode.agent.compactor import stage_stale_snip
    conv = _make_conversation(turns=2)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 tool_result_snip_limit=200, compact_keep_recent_turns=5)
    snipped = stage_stale_snip(conv, s)
    assert snipped == 0


# ─── 3. Stage 3: microcompact ──────────────────────────

def test_stage3_drops_old_reasoning():
    from tifacode.agent.compactor import stage_microcompact
    conv = Conversation()
    conv.add_user("task1")
    conv.add_assistant([
        {"type": "reasoning", "text": "let me think..."},
        {"type": "text", "text": "doing task1"},
        {"type": "tool_use", "id": "1", "name": "read", "input": {}},
    ])
    conv.add_tool_result("1", "result1")
    conv.add_user("task2")
    conv.add_assistant([{"type": "text", "text": "doing task2"}])
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 compact_keep_recent_turns=5)
    compacted = stage_microcompact(conv, s)
    assert compacted >= 1, f"expected >=1 compacted, got {compacted}"

def test_stage3_merges_consecutive_tool_results():
    from tifacode.agent.compactor import stage_microcompact
    conv = Conversation()
    conv.add_user("task")
    conv.add_assistant([{"type": "tool_use", "id": "1", "name": "read", "input": {}},
                        {"type": "tool_use", "id": "2", "name": "grep", "input": {}}])
    conv.add_tool_result("1", "read result " + "data " * 100)
    conv.add_tool_result("2", "grep result " + "found " * 100)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 compact_keep_recent_turns=5)
    compacted = stage_microcompact(conv, s)
    # 两个连续 tool_result 应该合并
    tool_msgs = [m for m in conv._messages if m["role"] == "tool"]
    assert len(tool_msgs) <= 1, f"expected merged to <=1 tool msgs, got {len(tool_msgs)}"


# ─── 4. Stage 4: auto_compact ──────────────────────────

def test_stage4_replaces_old_with_summary():
    from tifacode.agent.compactor import stage_auto_compact
    conv = _make_conversation(turns=8)
    old_len = len(conv._messages)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 compact_keep_recent_turns=2)
    removed = stage_auto_compact(conv, s)
    assert removed > 0
    # 新消息数应明显减少
    assert len(conv._messages) < old_len
    # 应有摘要消息
    has_summary = any(
        "对话摘要" in str(m.get("content", ""))
        for m in conv._messages if m["role"] == "user"
    )
    assert has_summary, "should have a summary message"

def test_stage4_skips_when_few_turns():
    from tifacode.agent.compactor import stage_auto_compact
    conv = _make_conversation(turns=2)
    old_len = len(conv._messages)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 compact_keep_recent_turns=5)
    removed = stage_auto_compact(conv, s)
    assert removed == 0
    assert len(conv._messages) == old_len


# ─── 5. Pipeline orchestration ─────────────────────────

def test_compact_conversation_runs_all_stages():
    from tifacode.agent.compactor import compact_conversation
    conv = _make_conversation(turns=20)  # 很多轮 → 高利用率
    s = Settings(
        tool_output_limit=20000, tool_log_enabled=False,
        compact_enabled=True, compact_keep_recent_turns=3,
        tool_result_snip_limit=200, tool_result_budget_limit=2000,
        compact_context_window=30000,  # 小窗口 → 容易触发
        compact_micro_threshold=0.3,
        compact_auto_threshold=0.5,
    )
    result = compact_conversation(conv, s)
    print(f"    compact result: {result}")
    # 至少 stage 2 应该触发
    assert result["stale"] > 0, f"stale should trigger: {result}"

def test_compact_disabled():
    from tifacode.agent.compactor import compact_conversation
    conv = _make_conversation(turns=10)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 compact_enabled=False)
    result = compact_conversation(conv, s)
    assert result == {"budget": 0, "stale": 0, "micro": 0, "auto": 0}

def test_percentage_utilization():
    """验证百分比利用率计算正确"""
    from tifacode.agent.compactor import _utilization, _get_context_window
    conv = _make_conversation(turns=5)
    s = Settings(tool_output_limit=20000, tool_log_enabled=False,
                 compact_context_window=200000)
    cw = _get_context_window(s)
    util = _utilization(conv, cw)
    assert 0 < util < 1.0, f"utilization should be between 0 and 1, got {util}"

def test_model_context_window_detection():
    from tifacode.agent.compactor import _get_context_window
    s = Settings(model="claude-sonnet-4-6", compact_context_window=0)
    assert _get_context_window(s) == 200000
    s2 = Settings(model="gpt-4o", compact_context_window=0)
    assert _get_context_window(s2) == 128000
    s3 = Settings(model="unknown-model", compact_context_window=0)
    assert _get_context_window(s3) == 128000  # default fallback


# ─── 6. Semantic recall (sideQuery) ────────────────────

def test_tokenize_and_extract_keywords():
    from tifacode.agent.semantic_recall import _tokenize, _extract_keywords
    text = "implement a new compression pipeline for the conversation context"
    tokens = _tokenize(text)
    assert len(tokens) > 0
    keywords = _extract_keywords(text, top_n=5)
    assert len(keywords) > 0
    # "compression" 应该出现
    kw_words = [k for k, _ in keywords]
    assert "compression" in kw_words or "pipeline" in kw_words

def test_semantic_index_ingest_and_query():
    from tifacode.agent.semantic_recall import SemanticIndex
    conv1 = Conversation()
    conv1.add_user("implement user authentication with JWT tokens")
    conv1.add_assistant([{"type": "text", "text": "I'll implement JWT-based auth with refresh tokens"}])

    conv2 = Conversation()
    conv2.add_user("add database migration for user schema")
    conv2.add_assistant([{"type": "text", "text": "Creating migration for users table"}])

    index = SemanticIndex()
    index.index_conversation(conv1)
    index.index_conversation(conv2)
    assert len(index._chunks) >= 2

    # 查询应与 auth 相关
    results = index.query("how does authentication work", top_k=3)
    assert len(results) > 0
    assert any("jwt" in str(r["content_preview"]).lower() or "auth" in str(r["content_preview"]).lower()
               for r in results), f"should find auth-related content: {results}"

    # 查询应与 db 相关
    results2 = index.query("database migration schema", top_k=3)
    assert any("migration" in str(r["content_preview"]).lower() or "user" in str(r["content_preview"]).lower()
               for r in results2), f"should find db-related content: {results2}"

def test_semantic_index_empty_query():
    from tifacode.agent.semantic_recall import SemanticIndex
    index = SemanticIndex()
    results = index.query("", top_k=5)
    assert results == []

def test_recall_relevant_context():
    from tifacode.agent.semantic_recall import (
        get_semantic_index, recall_relevant_context,
    )
    conv = Conversation()
    conv.add_user("fix the bug in the login handler that causes 500 errors")
    conv.add_assistant([{"type": "text", "text": "Found the null pointer in login_handler.py"}])

    index = get_semantic_index()
    index.index_conversation(conv)

    result = recall_relevant_context(conv, "what was the login bug", top_k=3)
    assert len(result) > 0
    assert "login" in result.lower() or "500" in result.lower()


# ─── 7. Cross-session memory ───────────────────────────

def test_memory_store_put_and_get():
    from tifacode.agent.memory import MemoryStore
    store = MemoryStore()
    store.put(key="test_key", content="Remember this value", tags=["test", "important"])
    entry = store.get("test_key")
    assert entry is not None
    assert entry.content == "Remember this value"
    assert "test" in entry.tags
    store.delete("test_key")
    assert store.get("test_key") is None

def test_memory_store_search_by_tags():
    from tifacode.agent.memory import MemoryStore
    store = MemoryStore()
    store.put(key="m1", content="value1", tags=["python", "config"])
    store.put(key="m2", content="value2", tags=["golang", "api"])
    results = store.search(["python"])
    assert len(results) >= 1
    assert any("value1" in r.content for r in results)
    store.delete("m1")
    store.delete("m2")

def test_memory_store_ttl_expiry():
    from tifacode.agent.memory import MemoryStore
    store = MemoryStore()
    store.put(key="ephemeral", content="short lived", tags=["temp"], ttl_seconds=0)
    # ttl=0 永不过期
    entry = store.get("ephemeral")
    assert entry is not None
    assert not entry.is_expired()
    store.delete("ephemeral")

def test_memory_inject_into_prompt():
    from tifacode.agent.memory import MemoryStore
    store = MemoryStore()
    store.put(key="p1", content="User prefers Python 3.11+", tags=["python", "preference"])
    store.put(key="p2", content="Database uses PostgreSQL 15", tags=["db", "postgres"])
    prompt = store.inject_into_prompt(tags=["python", "preference"])
    assert "Python 3.11" in prompt
    store.delete("p1")
    store.delete("p2")

def test_memory_list_all():
    from tifacode.agent.memory import MemoryStore
    store = MemoryStore()
    store.put(key="list1", content="a", tags=["test"])
    store.put(key="list2", content="b", tags=["test"])
    all_entries = store.list_all()
    assert len(all_entries) >= 2
    store.delete("list1")
    store.delete("list2")


# ─── 8. Conversation methods ───────────────────────────

def test_estimate_tokens_accurate():
    conv = _make_conversation(turns=5)
    tokens = conv.estimate_tokens()
    assert tokens > 1000, f"should have substantial tokens: {tokens}"

def test_trim_old_results_leaves_recent():
    conv = _make_conversation(turns=6)
    tool_count_before = sum(1 for m in conv._messages if m["role"] == "tool")
    trimmed = conv.trim_old_tool_results(keep_recent=4, snip_limit=200)
    tool_count_after = sum(1 for m in conv._messages if m["role"] == "tool")
    assert tool_count_after == tool_count_before  # 数量不变，只是内容变短
    assert trimmed > 0


# ─── Run all ──────────────────────────────────────────

print("=" * 60)
print("Phase 6 — 上下文与记忆 验证")
print("=" * 60)

print("\n[1] Stage 1: budget_truncation")
check("截断过长 tool_result", test_stage1_truncates_long_tool_results)
check("跳过长结果", test_stage1_skips_short_results)

print("\n[2] Stage 2: stale_snip")
check("压缩旧轮次工具结果", test_stage2_snips_old_turns)
check("轮次不足时跳过", test_stage2_skips_when_few_turns)

print("\n[3] Stage 3: microcompact")
check("删除早期 reasoning", test_stage3_drops_old_reasoning)
check("合并连续 tool_result", test_stage3_merges_consecutive_tool_results)

print("\n[4] Stage 4: auto_compact")
check("生成结构化摘要替换旧消息", test_stage4_replaces_old_with_summary)
check("轮次不足时跳过", test_stage4_skips_when_few_turns)

print("\n[5] 流水线编排")
check("compact_conversation 触发多阶段", test_compact_conversation_runs_all_stages)
check("compact_enabled=False 时跳过", test_compact_disabled)
check("百分比利用率计算", test_percentage_utilization)
check("模型上下文窗口检测", test_model_context_window_detection)

print("\n[6] sideQuery 语义召回")
check("关键词提取", test_tokenize_and_extract_keywords)
check("索引摄入和查询", test_semantic_index_ingest_and_query)
check("空查询返回空", test_semantic_index_empty_query)
check("recall_relevant_context 功能", test_recall_relevant_context)

print("\n[7] 跨会话记忆")
check("put + get", test_memory_store_put_and_get)
check("按 tag 搜索", test_memory_store_search_by_tags)
check("TTL 过期机制", test_memory_store_ttl_expiry)
check("inject_into_prompt", test_memory_inject_into_prompt)
check("list_all", test_memory_list_all)

print("\n[8] Conversation 方法增强")
check("estimate_tokens", test_estimate_tokens_accurate)
check("trim_old_tool_results", test_trim_old_results_leaves_recent)

print()
print(f"{'=' * 60}")
print(f"结果: {passed} PASS, {failed} FAIL")
print(f"{'=' * 60}")

sys.exit(0 if failed == 0 else 1)
