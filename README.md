# TifaCode

[中文版本](README_CN.md)

![tifa—image](image.jpg)
A lightweight local Coding Agent CLI for long-running, multi-step programming tasks. Designed around controllable tool execution, streaming output, and session persistence.

---

## Features

- **Multi-Provider Agent Loop** — Anthropic / OpenAI / DeepSeek backends, streaming responses, multi-turn tool execution
- **Rich CLI** — Interactive REPL with multi-line input (Enter to send, Shift+Enter for newline), Markdown streaming display, ANSI splash screen
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
tifacode --permission-mode plan               # read-only planning mode
tifacode --resume                             # resume last session
tifacode --list-sessions                      # list saved sessions
```

### REPL Commands

| Command       | Description        |
|---------------|--------------------|
| `/help`       | Show help          |
| `/new [name]` | Create and switch to a session |
| `/switch <name>` | Switch to an existing session |
| `/clear`      | Clear session      |
| `/exit`       | Quit               |
| `/sessions`   | List saved sessions|
| `/model`      | Show current model |
| `/permissions`| Show permission mode |

### Common Commands

```bash
# Start the default interactive session
tifacode

# Run a single task
tifacode "Read README and summarize the project"

# Create or enter a named session
tifacode --session refactor-auth

# List saved sessions
tifacode --list-sessions

# Resume the latest session
tifacode --resume

# Select provider and model
tifacode --provider openai --model gpt-4o

# Use read-only planning mode
tifacode --permission-mode plan

# Allow edits while Bash still requires confirmation
tifacode --permission-mode acceptEdits
```

Common interactive commands:

```text
/help                 Show REPL commands
/new bugfix-login     Create and switch to bugfix-login
/new                  Create an auto-named session
/switch refactor-auth Switch to an existing session
/sessions             List saved sessions
/permissions          Show permission mode
/clear                Clear the current session
/exit                 Quit
```

### Permission Modes

| Mode | Behavior |
|------|----------|
| `default` | Read tools are allowed; write/edit/Bash require confirmation |
| `plan` | Only read tools are allowed; write/edit/Bash are denied |
| `acceptEdits` | Read/write/edit are allowed; Bash requires confirmation |
| `bypassPermissions` | Skips tool confirmation while keeping built-in tool safety checks |
| `dontAsk` | Only read tools are allowed; tools requiring confirmation are denied |

Example `~/.tifacode/config.yaml`:

```yaml
permission_mode: default
permission_allow_tools: []
permission_deny_tools: []
tool_log_enabled: true
tool_output_limit: 20000
```

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
