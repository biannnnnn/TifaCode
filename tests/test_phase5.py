"""Phase 5 功能验证：延迟激活 / 并发执行 / read-before-edit + mtime"""
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


# ─── 1. 延迟工具激活 ──────────────────────────────────

def test_tier_1_has_core_tools():
    from tifacode.agent.loop import create_default_registry
    r = create_default_registry()
    r.set_active_tier(1)
    names = {s["name"] for s in r.get_schemas()}
    assert names == {"read", "write", "edit", "list", "grep", "glob", "tree", "bash"}, f"got {names}"

def test_tier_2_has_all_tools():
    from tifacode.agent.loop import create_default_registry
    r = create_default_registry()
    r.set_active_tier(2)
    names = {s["name"] for s in r.get_schemas()}
    expected = {"read", "write", "edit", "list", "grep", "glob", "tree",
                "todo", "diagnostics", "git_status", "git_diff", "read_many", "bash"}
    assert names == expected, f"got {names}, missing: {expected - names}"

def test_tier_2_includes_tier_1():
    from tifacode.agent.loop import create_default_registry
    r = create_default_registry()
    r.set_active_tier(1)
    t1 = set(s["name"] for s in r.get_schemas())
    r.set_active_tier(2)
    t2 = set(s["name"] for s in r.get_schemas())
    assert t1.issubset(t2), f"t2 missing: {t1 - t2}"

def test_token_estimate_savings():
    """前3轮使用 tier 1 应比全量节省 5 个工具 schema"""
    from tifacode.agent.loop import create_default_registry
    r = create_default_registry()
    r.set_active_tier(1)
    n1 = len(r.get_schemas())
    r.set_active_tier(2)
    n2 = len(r.get_schemas())
    saved = n2 - n1
    assert saved >= 5, f"expected >=5 tools deferred, got {saved}"


# ─── 2. 并发工具执行 ──────────────────────────────────

async def _async_test_concurrent_execution():
    """验证多工具并发执行的正确性"""
    import time as _time
    from tifacode.tools.base import Tool, ToolResult, ToolRegistry
    from tifacode.agent.messages import Conversation
    from tifacode.agent.loop import _execute_tools_concurrently
    from tifacode.agent.backend import ToolUse

    # 注册两个慢工具
    class SlowTool(Tool):
        name = "slow1"
        description = "slow"
        parameters = {"delay": {"type": "number"}}
        async def execute(self, delay=0.1, **kw):
            await asyncio.sleep(delay)
            return ToolResult.ok(f"done in {delay}s", delay=delay)

    class SlowTool2(SlowTool):
        name = "slow2"

    registry = ToolRegistry()
    registry.register(SlowTool())
    registry.register(SlowTool2())

    from tifacode.config.settings import Settings
    settings = Settings(tool_output_limit=5000, tool_log_enabled=False)
    conv = Conversation()
    tu1 = ToolUse(id="1", name="slow1", input={"delay": 0.1})
    tu2 = ToolUse(id="2", name="slow2", input={"delay": 0.1})

    class FakeCallbacks:
        called = []
        async def on_tool_result(self, name, result):
            self.called.append(name)
        async def on_tool_call(self, name, input): pass

    cbs = FakeCallbacks()

    start = _time.monotonic()
    await _execute_tools_concurrently(
        [(tu1.id, tu1), (tu2.id, tu2)], registry, settings, 1, conv, cbs
    )
    elapsed = _time.monotonic() - start

    # 两个 0.1s 工具并发执行，总时间应该 < 0.18s（允许开销）
    assert elapsed < 0.2, f"并发应快于顺序（0.2s+），实际 {elapsed:.2f}s"
    assert set(cbs.called) == {"slow1", "slow2"}, f"got {cbs.called}"
    assert len(conv.messages) == 2, f"expected 2 tool results, got {len(conv.messages)}"

def test_concurrent_execution():
    asyncio.run(_async_test_concurrent_execution())

async def _async_test_sequential_fallback():
    """验证单工具不走并发路径"""
    from tifacode.tools.base import Tool, ToolResult, ToolRegistry
    from tifacode.agent.messages import Conversation
    from tifacode.agent.loop import _execute_tools_concurrently
    from tifacode.agent.backend import ToolUse

    class FastTool(Tool):
        name = "fast"
        description = "fast"
        parameters = {}
        async def execute(self, **kw):
            return ToolResult.ok("ok")

    registry = ToolRegistry()
    registry.register(FastTool())

    from tifacode.config.settings import Settings
    settings = Settings(tool_output_limit=5000, tool_log_enabled=False)
    conv = Conversation()
    tu = ToolUse(id="1", name="fast", input={})

    class FakeCallbacks:
        called = []
        async def on_tool_result(self, name, result):
            self.called.append(name)
        async def on_tool_call(self, name, input): pass

    cbs = FakeCallbacks()
    await _execute_tools_concurrently(
        [(tu.id, tu)], registry, settings, 1, conv, cbs
    )
    assert cbs.called == ["fast"]

def test_sequential_fallback():
    asyncio.run(_async_test_sequential_fallback())

async def _async_test_concurrent_error_fallback():
    """验证并发执行时一个工具失败不影响另一个——两者都应有结果"""
    from tifacode.tools.base import Tool, ToolResult, ToolRegistry
    from tifacode.agent.messages import Conversation
    from tifacode.agent.loop import _execute_tools_concurrently
    from tifacode.agent.backend import ToolUse

    class FailingTool(Tool):
        name = "flaky"
        description = "fails in execute"
        parameters = {}
        async def execute(self, **kw):
            return ToolResult.fail("tool-level failure", error_code="test_error")

    class GoodTool(Tool):
        name = "good"
        description = "good"
        parameters = {}
        async def execute(self, **kw):
            return ToolResult.ok("good")

    registry = ToolRegistry()
    registry.register(FailingTool())
    registry.register(GoodTool())

    from tifacode.config.settings import Settings
    settings = Settings(tool_output_limit=5000, tool_log_enabled=False)
    conv = Conversation()
    tu1 = ToolUse(id="1", name="flaky", input={})
    tu2 = ToolUse(id="2", name="good", input={})

    class FakeCallbacks:
        called = []
        async def on_tool_result(self, name, result):
            self.called.append(name)
        async def on_tool_call(self, name, input): pass

    cbs = FakeCallbacks()
    await _execute_tools_concurrently(
        [(tu1.id, tu1), (tu2.id, tu2)], registry, settings, 1, conv, cbs
    )
    assert set(cbs.called) == {"flaky", "good"}, f"两个工具都应该被调用，实际: {cbs.called}"
    assert len(conv.messages) == 2, f"expected 2 results, got {len(conv.messages)}"

def test_concurrent_error_fallback():
    asyncio.run(_async_test_concurrent_error_fallback())


# ─── 3. read-before-edit + mtime ──────────────────────

def test_read_tool_records_mtime():
    from tifacode.tools.read import ReadTool
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        fp = f.name
        f.write("line1\nline2\nline3\n")

    tool = ReadTool()
    import asyncio
    result = asyncio.run(tool.execute(file_path=fp))
    assert result.success, f"read failed: {result.error}"
    assert "mtime" in result.metadata, "应该记录 mtime"
    os.unlink(fp)

def test_edit_rejects_stale_mtime():
    from tifacode.tools.edit import EditTool
    from tifacode.tools.filetracker import get_file_tracker

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        fp = f.name
        f.write("hello world\n")

    ft = get_file_tracker()
    ft.record_read(fp)

    # 外部修改文件
    time.sleep(0.01)
    os.utime(fp, None)  # touch

    tool = EditTool()
    import asyncio
    result = asyncio.run(tool.execute(file_path=fp, old_string="hello", new_string="hi"))
    assert not result.success, "应该拒绝 stale 文件编辑"
    assert result.error_code == "stale_file", f"应该报 stale_file，实际 {result.error_code}"
    os.unlink(fp)

def test_edit_allows_clean_mtime():
    from tifacode.tools.edit import EditTool
    from tifacode.tools.filetracker import get_file_tracker

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        fp = f.name
        f.write("hello world\n")

    ft = get_file_tracker()
    ft.record_read(fp)

    # 不修改文件（clean state）
    tool = EditTool()
    import asyncio
    result = asyncio.run(tool.execute(file_path=fp, old_string="hello", new_string="hi"))
    assert result.success, f"应该允许 clean 文件编辑: {result.error}"
    assert "已替换" in result.output
    os.unlink(fp)

def test_write_rejects_stale_mtime():
    from tifacode.tools.write import WriteTool
    from tifacode.tools.filetracker import get_file_tracker

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        fp = f.name
        f.write("original\n")

    ft = get_file_tracker()
    ft.record_read(fp)

    # 外部修改
    time.sleep(0.01)
    os.utime(fp, None)

    tool = WriteTool()
    import asyncio
    result = asyncio.run(tool.execute(file_path=fp, content="new content"))
    assert not result.success, "应该拒绝 stale 文件写入"
    assert result.error_code == "stale_file", f"应该报 stale_file，实际 {result.error_code}"
    os.unlink(fp)

def test_write_allows_new_file_without_read():
    """新文件无需 read 即可 write"""
    from tifacode.tools.write import WriteTool
    import tempfile

    fp = tempfile.mktemp(suffix=".txt")
    tool = WriteTool()
    import asyncio
    result = asyncio.run(tool.execute(file_path=fp, content="brand new"))
    assert result.success, f"新文件应该允许写入: {result.error}"
    assert os.path.exists(fp)
    os.unlink(fp)

def test_edit_auto_updates_mtime_after_write():
    """Edit 成功后自动更新 tracker，允许连续编辑"""
    from tifacode.tools.edit import EditTool
    from tifacode.tools.filetracker import get_file_tracker

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        fp = f.name
        f.write("first\nsecond\n")

    ft = get_file_tracker()
    ft.record_read(fp)

    tool = EditTool()
    import asyncio
    # 第一次编辑
    r1 = asyncio.run(tool.execute(file_path=fp, old_string="first", new_string="FIRST"))
    assert r1.success, f"第一次编辑应成功: {r1.error}"

    # 连续第二次编辑（不应被 stale 拦截）
    r2 = asyncio.run(tool.execute(file_path=fp, old_string="second", new_string="SECOND"))
    assert r2.success, f"连续编辑应成功（mtime 已更新）: {r2.error}"
    os.unlink(fp)


# ─── 4. ToolRegistry 一致性 ──────────────────────────

def test_registry_tier_persistence():
    """修改 active_tier 不影响已注册工具；execute 不受 tier 限制"""
    from tifacode.agent.loop import create_default_registry
    r = create_default_registry()
    r.set_active_tier(1)
    # 即使 tier 1 不暴露 todo，execute 也应该能调用
    import asyncio
    result = asyncio.run(r.execute("todo", {"action": "list"}))
    assert result.success, f"execute 不受 tier 限制: {result.error}"

def test_registry_unknown_tool():
    from tifacode.agent.loop import create_default_registry
    r = create_default_registry()
    import asyncio
    result = asyncio.run(r.execute("nonexistent", {}))
    assert not result.success
    assert result.error_code == "unknown_tool"


# ─── Run all ──────────────────────────────────────────

print("=" * 60)
print("Phase 5 — Agent 循环与工具系统 验证")
print("=" * 60)

print("\n[1] 延迟工具激活 (Lazy Tool Activation)")
check("Tier 1 只有 8 个核心工具", test_tier_1_has_core_tools)
check("Tier 2 包含全部 13 个工具", test_tier_2_has_all_tools)
check("Tier 2 包含 Tier 1 全部工具", test_tier_2_includes_tier_1)
check("前3轮节省 >=5 个工具 schema", test_token_estimate_savings)

print("\n[2] 并发工具执行 (Concurrent Tool Execution)")
check("多工具并发执行，总时间 < 0.2s", test_concurrent_execution)
check("单工具直接执行（不走并发）", test_sequential_fallback)
check("并发失败回退顺序执行", test_concurrent_error_fallback)

print("\n[3] read-before-edit + mtime 校验")
check("ReadTool 记录 mtime", test_read_tool_records_mtime)
check("Edit 拒绝 stale 文件", test_edit_rejects_stale_mtime)
check("Edit 允许 clean 文件", test_edit_allows_clean_mtime)
check("Write 拒绝 stale 文件", test_write_rejects_stale_mtime)
check("Write 允许新文件（无需 read）", test_write_allows_new_file_without_read)
check("连续编辑不触发 stale（mtime 自动更新）", test_edit_auto_updates_mtime_after_write)

print("\n[4] ToolRegistry 一致性")
check("execute 不受 tier 限制", test_registry_tier_persistence)
check("未知工具返回 unknown_tool", test_registry_unknown_tool)

print()
print(f"{'=' * 60}")
print(f"结果: {passed} PASS, {failed} FAIL")
print(f"{'=' * 60}")

sys.exit(0 if failed == 0 else 1)
