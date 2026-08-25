from unittest.mock import MagicMock

import pytest
import requests

from ghost_protocol.application.llm_provider import (
    LLMModelNotFoundError,
    LLMRequest,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from ghost_protocol.application.ollama_client import OllamaClient


def _response(payload, *, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = str(payload)
    return response


def test_ollama_client_sends_local_json_chat_payload():
    fake_session = MagicMock()
    fake_session.post.return_value = _response(
        {
            "model": "qwen2.5:3b",
            "message": {"role": "assistant", "content": '{"topic":"테스트"}'},
            "prompt_eval_count": 12,
            "eval_count": 8,
            "total_duration": 123,
        }
    )
    client = OllamaClient(model="qwen2.5:3b", session=fake_session)

    result = client.generate(
        LLMRequest(
            task="suggest_topic",
            system="s",
            prompt="p",
            temperature=0.4,
            max_output_tokens=256,
        )
    )

    assert result.text == '{"topic":"테스트"}'
    assert result.model == "qwen2.5:3b"
    assert result.usage == {
        "prompt_eval_count": 12,
        "eval_count": 8,
        "total_duration": 123,
    }
    payload = fake_session.post.call_args.kwargs["json"]
    assert payload["stream"] is False
    assert payload["format"] == "json"
    assert payload["model"] == "qwen2.5:3b"
    assert payload["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "p"},
    ]
    assert payload["options"] == {
        "temperature": 0.4,
        "num_predict": 256,
        "num_ctx": 4096,
    }
    assert payload["keep_alive"] == "10m"
    assert "api_key" not in payload
    assert fake_session.post.call_args.kwargs["timeout"] == 120.0


def test_ollama_client_forwards_json_schema_to_format():
    fake_session = MagicMock()
    fake_session.post.return_value = _response(
        {
            "model": "qwen2.5:7b",
            "message": {"role": "assistant", "content": '{"ok":true}'},
        }
    )
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    client = OllamaClient(model="qwen2.5:7b", session=fake_session)

    client.generate(
        LLMRequest(
            task="schema_test",
            system="s",
            prompt="p",
            json_schema=schema,
        )
    )

    payload = fake_session.post.call_args.kwargs["json"]
    assert payload["format"] == schema


def test_ollama_health_lists_models_without_auth_or_request_body():
    fake_session = MagicMock()
    fake_session.get.return_value = _response(
        {"models": [{"name": "qwen2.5:3b"}, {"name": "other:latest"}]}
    )
    client = OllamaClient(model="qwen2.5:3b", session=fake_session)

    result = client.health()

    assert result == {
        "ok": True,
        "model": "qwen2.5:3b",
        "models": ["qwen2.5:3b", "other:latest"],
        "model_available": True,
    }
    fake_session.get.assert_called_once_with(
        "http://127.0.0.1:11434/api/tags",
        timeout=120.0,
    )
    assert fake_session.get.call_args.kwargs.get("headers") is None
    assert fake_session.get.call_args.kwargs.get("json") is None


def test_ollama_client_rejects_non_loopback_urls():
    with pytest.raises(ValueError, match="loopback"):
        OllamaClient(base_url="http://192.168.1.20:11434", model="qwen2.5:3b")

    with pytest.raises(ValueError, match="loopback"):
        OllamaClient(base_url="http://0.0.0.0:11434", model="qwen2.5:3b")


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (requests.exceptions.ConnectionError("offline"), LLMUnavailableError),
        (requests.exceptions.Timeout("slow"), LLMTimeoutError),
    ],
)
def test_ollama_client_maps_transport_errors(exception, expected):
    fake_session = MagicMock()
    fake_session.post.side_effect = exception
    client = OllamaClient(model="qwen2.5:3b", session=fake_session)

    with pytest.raises(expected):
        client.generate(LLMRequest(task="task", system="s", prompt="p"))


def test_ollama_client_maps_404_to_model_not_found():
    fake_session = MagicMock()
    fake_session.post.return_value = _response(
        {"error": "model 'qwen2.5:3b' not found"}, status_code=404
    )
    client = OllamaClient(model="qwen2.5:3b", session=fake_session)

    with pytest.raises(LLMModelNotFoundError):
        client.generate(LLMRequest(task="task", system="s", prompt="p"))


def test_ollama_client_maps_server_errors_to_unavailable():
    fake_session = MagicMock()
    fake_session.post.return_value = _response({"error": "failed"}, status_code=500)
    client = OllamaClient(model="qwen2.5:3b", session=fake_session)

    with pytest.raises(LLMUnavailableError):
        client.generate(LLMRequest(task="task", system="s", prompt="p"))


def test_ollama_client_maps_malformed_json_and_response_shape():
    fake_session = MagicMock()
    malformed = _response(None)
    malformed.json.side_effect = ValueError("not json")
    fake_session.post.return_value = malformed
    client = OllamaClient(model="qwen2.5:3b", session=fake_session)

    with pytest.raises(LLMResponseError):
        client.generate(LLMRequest(task="task", system="s", prompt="p"))

    fake_session.post.return_value = _response({"message": {"content": 123}})
    with pytest.raises(LLMResponseError):
        client.generate(LLMRequest(task="task", system="s", prompt="p"))
