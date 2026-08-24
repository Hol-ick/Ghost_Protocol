import pytest

from ghost_protocol.application.llm_provider import LLMUnavailableError
from ghost_protocol.brain import GhostBrain


class _OfflineProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        raise LLMUnavailableError("Ollama is unavailable")


def test_generation_does_not_fallback_to_a_remote_provider():
    provider = _OfflineProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:3b")

    with pytest.raises(LLMUnavailableError):
        brain._generate_content_paced(label="unit-test", prompt="hello")

    assert provider.calls == 1
    assert brain.fallback_model_names == ("qwen2.5:7b",)
