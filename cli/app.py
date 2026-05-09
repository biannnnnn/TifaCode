from __future__ import annotations

import logging
import sys
from typing import Any

try:
    import gnureadline as readline  # macOS: 替换 libedit，修复 CJK 退格显示 bug
except ImportError:
    pass

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from tifacode.agent.backend import create_backend
from tifacode.agent.loop import AgentCallbacks, create_default_registry, run_agent_loop
from tifacode.agent.messages import Conversation
from tifacode.cli.display import render_splash
from tifacode.config.settings import Settings
from tifacode.session.store import SessionStore

logger = logging.getLogger(__name__)


_PT_STYLE = Style.from_dict({
    "prompt": "bold green",
    "bottom-toolbar": "italic",
})


def _create_pt_session() -> PromptSession:
    bindings = KeyBindings()

    @bindings.add("enter")
    def _(event: Any) -> None:
        """Enter 发送当前输入。"""
        event.app.exit(result=event.app.current_buffer.text)

    @bindings.add("escape", "enter")
    def _(event: Any) -> None:
        """Shift+Enter 换行。"""
        event.app.current_buffer.insert_text("\n")

    return PromptSession(
        multiline=True,
        key_bindings=bindings,
        style=_PT_STYLE,
        bottom_toolbar=" Enter 发送  |  Shift+Enter 换行  |  输入 exit 退出 ",
        wrap_lines=False,
    )


class CLICallbacks(AgentCallbacks):
    def __init__(self, live: Live, console: Console) -> None:
        self._live = live
        self._console = console
        self._current_tool_panels: list[Panel] = []
        self._accumulated: list[str] = []

    async def on_text_delta(self, text: str) -> None:
        self._accumulated.append(text)
        self._update_live()

    async def on_tool_call(self, name: str, input: dict[str, Any]) -> None:
        args = ", ".join(f"{k}={v!r}" for k, v in input.items())
        self._current_tool_panels.append(
            Panel(f"执行中...", title=f"🔧 {name}", border_style="cyan", title_align="left")
        )

    async def on_tool_result(self, name: str, result: str) -> None:
        preview = result[:800] + ("..." if len(result) > 800 else "")
        if self._current_tool_panels:
            self._current_tool_panels[-1] = Panel(
                preview, title=f"📋 {name}", border_style="dim", title_align="left"
            )

    async def on_turn_end(self, turn: int) -> None:
        self._current_tool_panels.clear()

    async def on_confirm_bash(self, command: str) -> bool:
        # 在 live 外部显示确认提示
        self._live.stop()
        try:
            resp = input(f"  ⚠ 执行命令: {command[:100]} [Y/n] ").strip().lower()
            return resp in ("", "y", "yes")
        finally:
            self._live.start()

    def _update_live(self) -> None:
        md = Markdown("".join(self._accumulated))
        renderables: list = [md]
        renderables.extend(self._current_tool_panels)
        self._live.update(Panel.group(*renderables) if len(renderables) > 1 else md)

    def reset(self) -> None:
        self._accumulated.clear()
        self._current_tool_panels.clear()


async def run_interactive(settings: Settings, session_name: str) -> None:
    console = Console()
    store = SessionStore()

    conversation: Conversation
    if store.exists(session_name):
        conversation = store.load(session_name)
        console.print(f"[dim]已恢复会话 '{session_name}'[/dim]")
    else:
        conversation = Conversation()
        console.print(f"[dim]新会话 '{session_name}'[/dim]")

    backend = create_backend(settings)
    registry = create_default_registry(settings)

    # ANSI splash 直接写入 stdout，避免 Rich 处理
    sys.stdout.write(render_splash() + "\n")
    sys.stdout.flush()
    console.print()

    pt_session = _create_pt_session()

    while True:
        # 顶部边框
        w = console.width
        console.print("┌" + "─" * (w - 2) + "┐", style="dim")

        try:
            user_input = await pt_session.prompt_async(
                [("class:prompt", "> ")],
            )
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见[/dim]")
            break

        # 底部边框
        console.print("└" + "─" * (w - 2) + "┘", style="dim")

        if user_input is None:
            continue

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.lower() == "exit":
            console.print("[dim]再见[/dim]")
            break

        if user_input.startswith("/"):
            action = _handle_slash_command(user_input, console, settings)
            if user_input in ("/exit", "/quit", "/q"):
                break
            if action == "clear":
                conversation = Conversation()
                store.save(session_name, conversation)
            continue

        conversation.add_user(user_input)

        with Live(Text("思考中..."), console=console, refresh_per_second=10, transient=False) as live:
            callbacks = CLICallbacks(live, console)
            try:
                await run_agent_loop(conversation, backend, registry, settings, callbacks)
            except Exception as e:
                live.stop()
                console.print(f"[red]错误: {e}[/red]")
                logger.exception("Agent loop error")
                live.start()

        console.print()  # 空行分隔
        store.save(session_name, conversation)


async def run_single_shot(settings: Settings, prompt: str, session_name: str) -> None:
    console = Console()
    store = SessionStore()

    conversation = Conversation()
    if store.exists(session_name):
        conversation = store.load(session_name)
        console.print(f"[dim]已恢复会话 '{session_name}'[/dim]")

    conversation.add_user(prompt)
    backend = create_backend(settings)
    registry = create_default_registry(settings)

    # ANSI splash 直接写入 stdout，避免 Rich 处理
    sys.stdout.write(render_splash() + "\n")
    sys.stdout.flush()
    console.print()

    with Live(Text("思考中..."), console=console, refresh_per_second=10, transient=False) as live:
        callbacks = CLICallbacks(live, console)
        try:
            await run_agent_loop(conversation, backend, registry, settings, callbacks)
        except Exception as e:
            live.stop()
            console.print(f"[red]错误: {e}[/red]")
            logger.exception("Agent loop error")

    console.print()
    store.save(session_name, conversation)


def _handle_slash_command(cmd: str, console: Console, settings: Settings) -> str | None:
    parts = cmd.split(maxsplit=1)
    name = parts[0].lower()

    if name in ("/exit", "/quit", "/q"):
        console.print("[dim]再见[/dim]")
    elif name == "/help":
        console.print(
            Panel(
                "命令:\n"
                "  /help      显示帮助\n"
                "  /clear     清空当前会话\n"
                "  /exit      退出程序\n"
                "  /sessions  列出已保存的会话\n"
                "  /model     显示当前模型",
                title="帮助",
                border_style="dim",
            )
        )
    elif name == "/clear":
        console.print("[dim]会话已清空（下次输入将开始新对话）[/dim]")
        return "clear"
    elif name == "/sessions":
        store = SessionStore()
        sessions = store.list_sessions()
        if sessions:
            console.print("\n".join(f"  • {s}" for s in sessions))
        else:
            console.print("[dim]无已保存的会话[/dim]")
    elif name == "/model":
        console.print(f"  provider: {settings.provider}\n  model: {settings.model}")
    else:
        console.print(f"[dim]未知命令: {name}，输入 /help 查看帮助[/dim]")
    return None
