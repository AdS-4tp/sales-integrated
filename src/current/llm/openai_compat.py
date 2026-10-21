"""Any OpenAI-compatible chat endpoint: Ollama, vLLM, llama.cpp server, Groq."""
from __future__ import annotations

import time
from typing import Any

import httpx


class OpenAICompatBackend:
    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        tiers: frozenset[str],
        *,
        local: bool,
        api_key: str = "",
        timeout: float = 120.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.tiers = tiers
        self.local = local
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout = timeout
        self._checked_at = 0.0
        self._ok = False

    def available(self) -> bool:
        # Cache the probe so a down server does not slow every request.
        if time.monotonic() - self._checked_at < 30:
            return self._ok
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers, timeout=2.0)
            self._ok = r.status_code < 500
        except httpx.HTTPError:
            self._ok = False
        self._checked_at = time.monotonic()
        return self._ok

    def complete(
        self,
        task: str,
        system: str,
        prompt: str,
        *,
        json_mode: bool = False,
        context: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=self._headers,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
