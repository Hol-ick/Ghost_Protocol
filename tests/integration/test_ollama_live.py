"""Opt-in integration checks for the local Ollama runtime.

Run with ``RUN_OLLAMA_LIVE=1 python -m pytest tests/integration/test_ollama_live.py -q``.
The default test suite never requires a running model server.
"""

from __future__ import annotations

import json
import os

import pytest

from ghost_protocol.application.llm_provider import LLMRequest
from ghost_protocol.application.ollama_client import OllamaClient


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_LIVE") != "1",
    reason="set RUN_OLLAMA_LIVE=1 to exercise the local Ollama runtime",
)


def _client() -> OllamaClient:
    return OllamaClient(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        model=os.getenv("OLLAMA_MODEL", "qwen2.5:3b"),
        timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SEC", "120")),
        num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "4096")),
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "10m"),
    )


def test_local_ollama_health_and_json_generation() -> None:
    client = _client()
    health = client.health()
    assert health["ok"] is True
    assert health["model_available"] is True, health

    response = client.generate(
        LLMRequest(
            task="integration_smoke",
            system="Return JSON only.",
            prompt="Return exactly {\"ok\": true, \"language\": \"ko\"}.",
            json_schema={
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "language": {"type": "string"},
                },
                "required": ["ok", "language"],
            },
            temperature=0.0,
            max_output_tokens=64,
        )
    )
    payload = json.loads(response.text)
    assert payload["ok"] is True
    assert payload["language"] == "ko"
    assert response.model == client.model
