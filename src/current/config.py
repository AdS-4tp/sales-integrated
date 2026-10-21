"""Runtime settings, read from environment variables with safe defaults.

Defaults are meant for local development: a mock LLM, a file-based SQLite
database and no way to send real email (the only mailer is the dry-run outbox).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    db_path: str = str(ROOT / "current.db")
    rules_path: str = str(ROOT / "config" / "rules.yaml")
    base_url: str = "http://localhost:8000"
    # Signs opt-out links. Must be changed in any shared deployment.
    secret: str = "dev-secret-change-me"
    # "mock" (deterministic, offline) or "ollama" (Qwen via an OpenAI-compatible API).
    llm: str = "mock"
    ollama_url: str = "http://localhost:11434/v1"
    small_model: str = "qwen2.5:7b-instruct"
    large_model: str = "qwen2.5:14b-instruct"
    # Hosted fallback. Only ever used for tasks that carry no personal data.
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    # Skips the go-live gate. Local demos only: nothing can be sent for real anyway.
    dev_unlock: bool = False

    def with_overrides(self, **kw) -> "Settings":
        return replace(self, **kw)


def from_env() -> Settings:
    d = Settings()
    return Settings(
        db_path=os.getenv("CURRENT_DB", d.db_path),
        rules_path=os.getenv("CURRENT_RULES", d.rules_path),
        base_url=os.getenv("CURRENT_BASE_URL", d.base_url).rstrip("/"),
        secret=os.getenv("CURRENT_SECRET", d.secret),
        llm=os.getenv("CURRENT_LLM", d.llm),
        ollama_url=os.getenv("OLLAMA_URL", d.ollama_url),
        small_model=os.getenv("CURRENT_SMALL_MODEL", d.small_model),
        large_model=os.getenv("CURRENT_LARGE_MODEL", d.large_model),
        groq_api_key=os.getenv("GROQ_API_KEY", d.groq_api_key),
        groq_model=os.getenv("GROQ_MODEL", d.groq_model),
        dev_unlock=os.getenv("CURRENT_DEV_UNLOCK", "") == "1",
    )
