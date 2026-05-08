# TifaCode

*[English](#english) | [中文](#中文)*

A lightweight local Coding Agent CLI built for long-running, multi-step programming tasks. Designed around controllable tool execution, stable context management, and clear permission boundaries.

---

## English

### Features

- **Agent Loop & Tools** — Compatible with Anthropic, OpenAI and DeepSeek backends, streaming output, 4 core tools (read/write/edit/bash), dangerous command detection
- **CLI with Rich** — Interactive REPL and single-shot modes, Markdown streaming display, session persistence & recovery
- **Permission System** — Built-in dangerous command blocklist, user confirmation for bash execution
- **Session Management** — Save/load named sessions to `~/.tifacode/sessions/`, resume interrupted work

### Quick Start

**Prerequisites:** Python 3.9+, API key for Anthropic / OpenAI / DeepSeek

```bash
# 1. Clone & install
git clone <repo-url> && cd TifaCode
pip install .

# 2. Set API key
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
export OPENAI_API_KEY="sk-..."          # OpenAI
export DEEPSEEK_API_KEY="sk-..."        # DeepSeek

# 3. Run
tifacode "List files in current directory"   # single-shot
tifacode                                      # interactive REPL
tifacode --provider openai                    # switch backend
tifacode --provider deepseek                  # use DeepSeek
tifacode --resume                             # resume last session
tifacode --list-sessions                      # list saved sessions
```

### Project Structure

```
TifaCode/
├── main.py            # Entry point
├── agent/             # Agent loop, LLM backends, message management
├── tools/             # Tool base + read/write/edit/bash
├── cli/               # Rich-based CLI interface
├── session/           # Session persistence
├── config/            # Configuration (YAML + env vars)
├── pyproject.toml
└── setup.py
```

---

## 中文

### 功能

- **Agent 循环与工具** — 兼容 Anthropic/OpenAI/DeepSeek 后端，流式输出，4 个核心工具（读/写/编辑文件、Shell 命令），危险命令检测
- **Rich CLI 界面** — 交互式 REPL 与单次执行两种模式，Markdown 流式渲染，会话持久化与恢复
- **权限系统** — 内置危险命令黑名单，Bash 命令执行前需用户确认
- **会话管理** — 命名会话保存至 `~/.tifacode/sessions/`，支持中断恢复

### 快速启动

**环境要求：** Python 3.9+，Anthropic / OpenAI / DeepSeek API Key

```bash
# 1. 克隆并安装
git clone <repo-url> && cd TifaCode
pip install .

# 2. 设置 API Key
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
export OPENAI_API_KEY="sk-..."          # OpenAI
export DEEPSEEK_API_KEY="sk-..."        # DeepSeek

# 3. 运行
tifacode "列出当前目录下的文件"           # 单次执行
tifacode                                  # 交互模式
tifacode --provider openai                # 切换后端
tifacode --provider deepseek              # 使用 DeepSeek
tifacode --resume                         # 恢复上次会话
tifacode --list-sessions                  # 列出已保存会话
```

### 项目结构

```
TifaCode/
├── main.py            # 入口
├── agent/             # Agent 循环、LLM 后端、消息管理
├── tools/             # 工具基类 + read/write/edit/bash
├── cli/               # 基于 Rich 的 CLI 界面
├── session/           # 会话持久化
├── config/            # 配置（YAML + 环境变量）
├── pyproject.toml
└── setup.py
```
