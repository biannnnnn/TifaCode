from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from tifacode.cli.app import run_interactive, run_single_shot
from tifacode.config.settings import load_settings
from tifacode.session.store import SessionStore


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tifacode",
        description="TifaCode: 面向 Harness Engineering 的轻量级本地 Coding Agent CLI",
    )
    parser.add_argument("prompt", nargs="?", help="单次任务提示词（不提供则进入交互模式）")
    parser.add_argument("--session", "-s", default="default", help="会话名称（默认 default）")
    parser.add_argument("--model", "-m", help="模型名称")
    parser.add_argument("--provider", "-p", choices=["anthropic", "openai", "deepseek"], help="LLM 后端")
    parser.add_argument("--resume", "-r", action="store_true", help="恢复上次会话")
    parser.add_argument("--list-sessions", action="store_true", help="列出已保存的会话")
    parser.add_argument("--debug", action="store_true", help="启用调试日志")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.list_sessions:
        store = SessionStore()
        sessions = store.list_sessions()
        if sessions:
            print("\n".join(sessions))
        else:
            print("无已保存的会话")
        return

    settings = load_settings()
    if args.model:
        settings.model = args.model
    if args.provider:
        settings.set_provider(args.provider, reset_model=not bool(args.model))

    session_name = args.session
    if args.resume:
        store = SessionStore()
        latest = store.latest_session_name()
        if latest and args.session == "default":
            session_name = latest

    if args.prompt:
        asyncio.run(run_single_shot(settings, args.prompt, session_name))
    else:
        asyncio.run(run_interactive(settings, session_name))


if __name__ == "__main__":
    main()
