"""Small, loopback-only HTTP adapter for a local Ollama server."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import requests

from .llm_provider import (
    LLMModelNotFoundError,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)


_LOOPBACK_HOSTNAMES = {"localhost", "localhost.localdomain"}
_USAGE_FIELDS = (
    "prompt_eval_count",
    "eval_count",
    "total_duration",
)


def _is_loopback_hostname(hostname: str) -> bool:
    hostname = hostname.rstrip(".").lower()
    if hostname in _LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


class OllamaClient:
    """Call Ollama's local ``/api/chat`` and ``/api/tags`` endpoints.

    Only loopback hosts are accepted.  No authentication, account, cookie, or
    session headers are added by this adapter; Ollama is expected to be a
    local process owned by the current machine.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str,
        timeout_seconds: float = 120.0,
        num_ctx: int = 4096,
        keep_alive: str = "10m",
        session: requests.Session | None = None,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must not be empty")
        self.model = model.strip()
        self.base_url = self._validate_base_url(base_url)

        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be numeric") from exc
        if timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout

        try:
            context = int(num_ctx)
        except (TypeError, ValueError) as exc:
            raise ValueError("num_ctx must be an integer") from exc
        if context <= 0:
            raise ValueError("num_ctx must be positive")
        self.num_ctx = context

        if not isinstance(keep_alive, str) or not keep_alive.strip():
            raise ValueError("keep_alive must not be empty")
        self.keep_alive = keep_alive.strip()
        self._session = session if session is not None else requests.Session()

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must not be empty")
        value = base_url.strip().rstrip("/")
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Ollama base_url must use http or https")
        if not parsed.hostname or not _is_loopback_hostname(parsed.hostname):
            raise ValueError("Ollama base_url must be loopback-only")
        if parsed.username or parsed.password:
            raise ValueError("Ollama base_url must not include credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("Ollama base_url must not include query or fragment")
        return value

    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}{endpoint}"

    @staticmethod
    def _response_detail(response: Any) -> str:
        try:
            text = str(getattr(response, "text", "")).strip()
        except Exception:
            text = ""
        return text[:500]

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        try:
            response = getattr(self._session, method)(
                self._url(endpoint),
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.exceptions.Timeout as exc:
            raise LLMTimeoutError(
                f"Ollama request timed out after {self.timeout_seconds:g}s"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise LLMUnavailableError("Ollama is unavailable") from exc
        except requests.exceptions.RequestException as exc:
            raise LLMUnavailableError(f"Ollama request failed: {exc}") from exc

        try:
            status_code = int(response.status_code)
        except (AttributeError, TypeError, ValueError) as exc:
            raise LLMResponseError("Ollama response has no valid status code") from exc

        if status_code >= 400:
            detail = self._response_detail(response)
            message = f"Ollama HTTP {status_code}"
            if detail:
                message = f"{message}: {detail}"
            if status_code == 404 and method == "post":
                raise LLMModelNotFoundError(message)
            if status_code >= 500:
                raise LLMUnavailableError(message)
            raise LLMResponseError(message)
        return response

    @staticmethod
    def _json(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, TypeError, requests.exceptions.RequestException) as exc:
            raise LLMResponseError("Ollama returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise LLMResponseError("Ollama response must be a JSON object")
        return payload

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not isinstance(request, LLMRequest):
            raise TypeError("request must be an LLMRequest")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "stream": False,
            # Ollama accepts either the legacy JSON mode or a JSON-schema
            # object.  Forward the shared contract instead of silently
            # discarding it at the adapter boundary.
            "format": request.json_schema or "json",
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
                "num_ctx": self.num_ctx,
            },
            "keep_alive": self.keep_alive,
        }
        response = self._request("post", "/api/chat", json=payload)
        raw = self._json(response)
        message = raw.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LLMResponseError("Ollama response is missing message.content")

        usage: dict[str, int] = {}
        for field in _USAGE_FIELDS:
            value = raw.get(field)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                usage[field] = int(value)

        response_model = raw.get("model")
        if not isinstance(response_model, str) or not response_model.strip():
            response_model = self.model
        return LLMResponse(
            text=message["content"],
            model=response_model,
            usage=usage,
            raw=raw,
        )

    def health(self) -> dict[str, Any]:
        """Return service health and whether the configured model is installed."""

        response = self._request("get", "/api/tags")
        raw = self._json(response)
        raw_models = raw.get("models")
        if not isinstance(raw_models, list):
            raise LLMResponseError("Ollama health response is missing models")

        model_names: list[str] = []
        for item in raw_models:
            if isinstance(item, dict):
                name = item.get("name")
            else:
                name = item
            if isinstance(name, str) and name.strip():
                model_names.append(name.strip())

        return {
            "ok": True,
            "model": self.model,
            "models": model_names,
            "model_available": self.model in model_names,
        }
