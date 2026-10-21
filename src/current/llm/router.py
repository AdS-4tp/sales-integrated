"""Picks a backend per task and per data class.

Two rules the rest of the app relies on:
  * ``personal`` data is only ever sent to backends marked ``local``.
  * If nothing allowed is available we raise. We never fall back silently to a
    weaker or less private backend.
"""
from __future__ import annotations

from typing import Any, Literal

from current.config import Settings
from current.llm.base import TASKS, Backend, NoBackendAvailable
from current.llm.mock import MockBackend
from current.llm.openai_compat import OpenAICompatBackend

DataClass = Literal["personal", "public"]

# Preferred tiers per task, most preferred first. Small model first for anything
# cheap; the larger model for writing and planning.
TASK_TIERS: dict[str, tuple[str, ...]] = {
    "classify": ("small",),
    "triage": ("small",),
    "guard_review": ("small",),
    "score": ("small", "large"),
    "draft": ("large", "small"),
    "plan": ("large", "small"),
}
assert set(TASK_TIERS) == set(TASKS)


class ModelRouter:
    def __init__(self, backends: list[Backend]) -> None:
        self.backends = backends

    def backend_for(
        self, task: str, data_class: DataClass, *, tier: str | None = None
    ) -> Backend:
        tiers = (tier,) if tier else TASK_TIERS[task]
        tried: list[str] = []
        for t in tiers:
            for b in self.backends:
                if t not in b.tiers:
                    continue
                if data_class == "personal" and not b.local:
                    continue
                tried.append(b.name)
                if b.available():
                    return b
        raise NoBackendAvailable(
            f"No available backend for task '{task}' with {data_class} data (tried {tried or 'none'})"
        )

    def complete(
        self,
        task: str,
        system: str,
        prompt: str,
        *,
        data_class: DataClass,
        json_mode: bool = False,
        context: dict[str, Any] | None = None,
        tier: str | None = None,
    ) -> tuple[str, str]:
        """Returns (text, backend name)."""
        b = self.backend_for(task, data_class, tier=tier)
        return b.complete(task, system, prompt, json_mode=json_mode, context=context), b.name


def build_router(s: Settings) -> ModelRouter:
    if s.llm == "mock":
        return ModelRouter([MockBackend()])
    backends: list[Backend] = [
        OpenAICompatBackend("ollama-small", s.ollama_url, s.small_model, frozenset({"small"}), local=True),
        OpenAICompatBackend("ollama-large", s.ollama_url, s.large_model, frozenset({"large"}), local=True),
    ]
    if s.groq_api_key:
        backends.append(
            OpenAICompatBackend(
                "groq", "https://api.groq.com/openai/v1", s.groq_model,
                frozenset({"small"}), local=False, api_key=s.groq_api_key,
            )
        )
    return ModelRouter(backends)
