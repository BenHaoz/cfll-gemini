"""配置加载：YAML 文件 + 环境变量。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
DEBUG_DIR = ROOT / "debug"

DIRECTIONS = [
    "马克思主义民族理论与政策",
    "中华民族学",
    "人类学与世界民族",
    "中华民族共同体学",
]


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class LLMSettings:
    provider: str = "gemini"  # gemini | anthropic | none
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    gemini_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-5"
    timeout: int = 180

    @property
    def available(self) -> bool:
        if self.provider == "gemini":
            return bool(self.gemini_api_key)
        if self.provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False


@dataclass
class MailSettings:
    host: str = ""
    port: int = 465
    user: str = ""
    password: str = ""
    sender: str = ""
    to: list[str] = field(default_factory=lambda: ["38064358@qq.com"])
    use_ssl: bool = True

    @property
    def available(self) -> bool:
        return bool(self.host and self.user and self.password and self.to)


@dataclass
class Settings:
    sources: dict[str, Any]
    keywords: dict[str, Any]
    guangxi: dict[str, Any]
    llm: LLMSettings
    mail: MailSettings
    lookback_days: int = 14


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def load_settings(config_dir: Path | None = None) -> Settings:
    cdir = config_dir or CONFIG_DIR
    sources = load_yaml(cdir / "sources.yaml")
    keywords = load_yaml(cdir / "keywords.yaml")
    guangxi = load_yaml(cdir / "guangxi.yaml")

    provider = _env("LLM_PROVIDER", "").lower()
    if not provider:
        if _env("GEMINI_API_KEY"):
            provider = "gemini"
        elif _env("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            provider = "none"
    llm = LLMSettings(
        provider=provider,
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_base_url=_env("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/"),
        gemini_model=_env("GEMINI_MODEL", "gemini-2.5-flash"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_base_url=_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-sonnet-5"),
        timeout=int(_env("LLM_TIMEOUT", "180") or 180),
    )

    port = int(_env("SMTP_PORT", "465") or 465)
    to_raw = _env("MAIL_TO", "38064358@qq.com")
    mail = MailSettings(
        host=_env("SMTP_HOST"),
        port=port,
        user=_env("SMTP_USER"),
        password=_env("SMTP_PASS"),
        sender=_env("MAIL_FROM") or _env("SMTP_USER"),
        to=[x.strip() for x in to_raw.replace(";", ",").split(",") if x.strip()],
        use_ssl=(_env("SMTP_SSL", "auto").lower() in ("1", "true", "yes")) or (_env("SMTP_SSL", "auto") == "auto" and port == 465),
    )
    lookback = int(_env("LOOKBACK_DAYS", str(sources.get("lookback_days", 14))))
    return Settings(sources=sources, keywords=keywords, guangxi=guangxi, llm=llm, mail=mail, lookback_days=lookback)
