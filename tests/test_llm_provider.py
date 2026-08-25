from dataclasses import FrozenInstanceError

import pytest

from ghost_protocol.application.llm_provider import (
    LLMModelNotFoundError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)


def test_llm_request_has_stable_json_contract_and_defensive_copy():
    schema = {"type": "object", "properties": {"topic": {"type": "string"}}}
    request = LLMRequest(
        task="judge_post",
        system="s",
        prompt="p",
        json_schema=schema,
    )

    assert request.task == "judge_post"
    assert request.json_schema == schema

    schema["properties"]["extra"] = {"type": "string"}
    assert "extra" not in request.json_schema["properties"]


def test_llm_request_normalizes_generation_limits_and_rejects_empty_task():
    request = LLMRequest(
        task="  suggest_topic  ",
        system="s",
        prompt="p",
        temperature=-1,
        max_output_tokens=0,
    )

    assert request.task == "suggest_topic"
    assert request.temperature == 0.0
    assert request.max_output_tokens == 1

    with pytest.raises(ValueError, match="task"):
        LLMRequest(task=" ", system="s", prompt="p")


def test_llm_request_is_frozen():
    request = LLMRequest(task="task", system="s", prompt="p")

    with pytest.raises(FrozenInstanceError):
        request.task = "other"


def test_llm_response_copies_usage_and_raw():
    usage = {"eval_count": 2}
    raw = {"message": {"content": "ok"}}
    response = LLMResponse(text="ok", model="qwen2.5:3b", usage=usage, raw=raw)

    usage["eval_count"] = 99
    raw["model"] = "other"
    assert response.usage == {"eval_count": 2}
    assert response.raw == {"message": {"content": "ok"}}


def test_provider_protocol_and_exception_hierarchy_are_available():
    class FakeProvider:
        def generate(self, request):
            return LLMResponse(text="{}", model="test", usage={}, raw={})

        def health(self):
            return {"ok": True}

    assert isinstance(FakeProvider(), LLMProvider)
    assert issubclass(LLMModelNotFoundError, LLMUnavailableError)
    assert issubclass(LLMTimeoutError, LLMUnavailableError)
    assert issubclass(LLMResponseError, Exception)
