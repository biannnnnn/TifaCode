# TifaCode

[English](README.md)
![tifa—image](image.jpg)
轻量级本地 Coding Agent CLI，面向多轮、多步骤编程任务。围绕可控工具执行、流式输出、会话持久化设计。

---

## 功能

- **多后端 Agent 循环** — 兼容 Anthropic / OpenAI / DeepSeek 后端，流式响应，多轮工具调用
- **Rich CLI 界面** — 交互式 REPL，多行输入（Enter 换行，Alt+Enter 发送），Markdown 流式渲染，ANSI 彩色启动画面
- **4 个核心工具** — 读取文件、写入文件、编辑文件、执行 Bash 命令
- **权限系统** — 危险命令黑名单拦截，Bash 命令执行前需用户确认
- **会话管理** — 命名会话保存至 `~/.tifacode/sessions/`，支持中断恢复
- **自动检测后端** — 根据已设置的 API Key 环境变量自动选择 provider

## 快速启动

**环境要求：** Python 3.9+，Anthropic / OpenAI / DeepSeek API Key

```bash
# 1. 克隆并安装
git clone <repo-url> && cd TifaCode
pip install .

# 2. 设置 API Key（只需设置一个，自动检测）
export DEEPSEEK_API_KEY="sk-..."        # DeepSeek
export ANTHROPIC_API_KEY="sk-ant-..."   # Anthropic
export OPENAI_API_KEY="sk-..."          # OpenAI

# 3. 运行
tifacode                                      # 交互模式
tifacode "列出当前目录下的文件"                   # 单次执行
tifacode --provider openai                    # 切换后端
tifacode --resume                             # 恢复上次会话
tifacode --list-sessions                      # 列出已保存会话
```

### REPL 命令

| 命令          | 说明             |
|---------------|------------------|
| `/help`       | 显示帮助         |
| `/clear`      | 清空当前会话      |
| `/exit`       | 退出程序         |
| `/sessions`   | 列出已保存会话    |
| `/model`      | 显示当前模型      |

## 项目结构

```
TifaCode/
├── main.py            # 入口
├── agent/             # Agent 循环、LLM 后端、消息管理
├── tools/             # 工具基类 + read/write/edit/bash
├── cli/               # Rich CLI 界面 + prompt_toolkit 输入
├── session/           # 会话持久化
├── config/            # 配置（YAML + 环境变量）
├── pyproject.toml
└── setup.py
```
