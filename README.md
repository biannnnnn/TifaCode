# TifaCode

[中文版本](README_CN.md)

![tifa—image](image.jpg)
A lightweight local Coding Agent CLI for long-running, multi-step programming tasks. Designed around controllable tool execution, streaming output, and session persistence.

---

## Features

- **Multi-Provider Agent Loop** — Anthropic / OpenAI / DeepSeek backends, streaming responses, multi-turn tool execution
- **Rich CLI** — Interactive REPL with multi-line input (Enter for newline, Alt+Enter to send), Markdown streaming display, ANSI splash screen
- **4 Core Tools** — Read, write, edit files + Bash shell commands
- **Permission System** — Dangerous command blocklist, user confirmation for bash execution
- **Session Management** — Save/load named sessions to `~/.tifacode/sessions/`, resume interrupted work
- **Auto Provider Detection** — Automatically picks the right backend based on available API keys

## Quick Start

**Prerequisites:** Python 3.9+, API key for Anthropic / OpenAI / DeepSeek

```bash
# 1. Clone & install
git clone <repo-url> && cd TifaCode
pip install .

# 2. Set API key (only one needed, auto-detected)
export DEEPSEEK_API_KEY="sk-..."        # DeepSeek
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
export OPENAI_API_KEY="sk-..."          # OpenAI

# 3. Run
tifacode                                      # interactive REPL
tifacode "List files in current directory"    # single-shot
tifacode --provider openai                    # switch backend
tifacode --resume                             # resume last session
tifacode --list-sessions                      # list saved sessions
```

### REPL Commands

| Command       | Description        |
|---------------|--------------------|
| `/help`       | Show help          |
| `/clear`      | Clear session      |
| `/exit`       | Quit               |
| `/sessions`   | List saved sessions|
| `/model`      | Show current model |

## Project Structure

```
TifaCode/
├── main.py            # Entry point
├── agent/             # Agent loop, LLM backends, message management
├── tools/             # Tool base + read/write/edit/bash
├── cli/               # Rich CLI + prompt_toolkit input
├── session/           # Session persistence
├── config/            # Configuration (YAML + env vars)
├── pyproject.toml
└── setup.py
```
