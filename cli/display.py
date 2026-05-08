from __future__ import annotations

from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()


def render_markdown(text: str) -> Markdown:
    return Markdown(text)


def render_tool_call(name: str, input: dict) -> RenderableType:
    args = ", ".join(f"{k}={v!r}" for k, v in input.items())
    return Text.from_markup(f"[bold cyan]🔧 {name}[/bold cyan]({args})")


def render_tool_result(result: str) -> Panel:
    preview = result[:500] + ("..." if len(result) > 500 else "")
    return Panel(preview, title="result", border_style="dim", title_align="left")


def render_user_message(text: str) -> Text:
    return Text(text, style="bold green")


def render_assistant_header() -> Text:
    return Text("TifaCode", style="bold blue")
