"""Thin client for a local model server.

Dev machine: Ollama (`ollama serve`, default http://localhost:11434) — easiest
install on Windows/Mac/Linux, pulls and manages GGUF weights itself.
Deployment target (Pi/N100): swap for llama-server directly — see
docs/PLAN.md §8, "skip Docker... run llama-server natively". Both speak an
HTTP chat-completions-shaped API, so only `base_url` and the request shape
below need to change, not the rest of this codebase.
"""

from __future__ import annotations

import dataclasses

import requests


@dataclasses.dataclass
class LLMConfig:
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:1.5b"  # placeholder until the §4 bake-off picks a winner
    max_tokens: int = 160
    temperature: float = 0.2
    timeout_s: float = 60.0


class OllamaClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()

    def chat(self, messages: list[dict]) -> str:
        resp = requests.post(
            f"{self.config.base_url}/api/chat",
            json={
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                },
            },
            timeout=self.config.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"].strip()

    def is_reachable(self) -> bool:
        try:
            r = requests.get(f"{self.config.base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False
