from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path.home() / ".tifacode"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
SESSION_DIR = CONFIG_DIR / "sessions"
TOOL_LOG_FILE = CONFIG_DIR / "tool_calls.jsonl"


def _load_dotenv() -> None:
    """加载 .env 文件中的环境变量（不覆盖已设置的）。
    按优先级查找：当前工作目录 > 用户 home 目录 > 包根目录。
    """
    candidates = [
        Path(".env"),
        Path.home() / ".tifacode" / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    env_file = None
    for c in candidates:
        if c.is_file():
            env_file = c
            break
    if env_file is None:
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if val and not os.getenv(key):
            os.environ[key] = val


DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "deepseek": "deepseek-v4-pro",
}


@dataclass
class Settings:
    provider: str = "anthropic"
    model: str = ""
    api_key: str = ""
    max_turns: int = 25
    bash_timeout: int = 120
    tool_output_limit: int = 20000
    retry_attempts: int = 3
    retry_initial_delay: float = 0.5
    retry_max_delay: float = 8.0
    tool_log_enabled: bool = True
    tool_log_file: str = ""
    tool_log_input_limit: int = 4000

    def __post_init__(self) -> None:
        if not self.model:
            self.model = DEFAULT_MODELS.get(self.provider, "gpt-4o")

    def set_provider(self, provider: str, reset_model: bool = False) -> None:
        self.provider = provider
        if reset_model:
            self.model = DEFAULT_MODELS.get(provider, "gpt-4o")

    @property
    def resolved_tool_log_file(self) -> Path:
        return Path(self.tool_log_file).expanduser() if self.tool_log_file else TOOL_LOG_FILE

    @property
    def anthropic_api_key(self) -> str:
        return self.api_key or os.getenv("ANTHROPIC_API_KEY", "")

    @property
    def openai_api_key(self) -> str:
        return self.api_key or os.getenv("OPENAI_API_KEY", "")

    @property
    def deepseek_api_key(self) -> str:
        return self.api_key or os.getenv("DEEPSEEK_API_KEY", "")


def _load_config_file() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return yaml.safe_load(f) or {}
    return {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(value)


PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


def _detect_provider() -> str:
    """按优先级检测第一个可用的 provider: 配置文件 > 环境变量 > anthropic。"""
    for name, env_var in PROVIDER_ENV.items():
        if os.getenv(env_var):
            return name
    return "anthropic"


def load_settings() -> Settings:
    _load_dotenv()
    file_cfg = _load_config_file()
    provider = file_cfg.get("provider", "")
    if not provider:
        provider = _detect_provider()
    merged: dict[str, Any] = {
        "provider": provider,
        "model": file_cfg.get("model", ""),
        "api_key": file_cfg.get("api_key", ""),
        "max_turns": int(file_cfg.get("max_turns", 25)),
        "bash_timeout": int(file_cfg.get("bash_timeout", 120)),
        "tool_output_limit": int(file_cfg.get("tool_output_limit", 20000)),
        "retry_attempts": int(file_cfg.get("retry_attempts", 3)),
        "retry_initial_delay": float(file_cfg.get("retry_initial_delay", 0.5)),
        "retry_max_delay": float(file_cfg.get("retry_max_delay", 8.0)),
        "tool_log_enabled": _as_bool(file_cfg.get("tool_log_enabled"), True),
        "tool_log_file": file_cfg.get("tool_log_file", ""),
        "tool_log_input_limit": int(file_cfg.get("tool_log_input_limit", 4000)),
    }
    return Settings(**merged)
