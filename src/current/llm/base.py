"""Backend interface and JSON helpers for the model layer."""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

# Every LLM call in the app names one of these tasks. The router uses the task
# to pick a tier; the mock backend uses it to know what to fake.
TASKS = ("classify", "score", "triage", "draft", "plan", "guard_review")


class NoBackendAvailable(RuntimeError):
    """No allowed backend can serve this task. Raised instead of falling back silently."""


class Backend(Protocol):
    name: str
    local: bool            # True when data never leaves infrastructure we control
    tiers: frozenset[str]  # subset of {"small", "large"}

    def available(self) -> bool: ...

    def complete(
        self,
        task: str,
        system: str,
        prompt: str,
        *,
        json_mode: bool = False,
        context: dict[str, Any] | None = None,
    ) -> str: ...


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model reply, tolerating prose or fences."""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return out if isinstance(out, dict) else None
