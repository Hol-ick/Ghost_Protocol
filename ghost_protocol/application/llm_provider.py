"""Common contracts for local language-model providers.

The application layer depends on these small value objects instead of a
provider SDK.  Keeping the transport-independent contract here makes the
Ollama adapter replaceable and keeps provider failures distinguishable at the
call boundary.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class LLMProviderError(RuntimeError):
    """Base class for errors raised while calling an LLM provider."""


class LLMUnavailableError(LLMProviderError):
    """The provider process or transport is unavailable."""


class LLMModelNotFoundError(LLMUnavailableError):
    """The provider is reachable, but the configured model is not installed."""


class LLMTimeoutError(LLMUnavailableError):
    """The provider did not answer within the configured timeout."""


class LLMResponseError(LLMProviderError):
    """The provider returned a response that violates the common contract."""


@dataclass(frozen=True)
class LLMRequest:
    """A provider-neutral generation request.

    ``json_schema`` is copied on construction so a caller cannot accidentally
    change the request after it has been handed to a provider.  The values are
    intentionally kept as plain dictionaries for JSON serialization by HTTP
    adapters.
    """

    task: str
    system: str
    prompt: str
    json_schema: dict[str, Any] | None = None
    temperature: float = 0.2
    max_output_tokens: int = 1024

    def __post_init__(self) -> None:
        if not isinstance(self.task, str):
            raise TypeError("task must be a string")
        task = self.task.strip()
        if not task:
            raise ValueError("task must not be empty")
        object.__setattr__(self, "task", task)

        if not isinstance(self.system, str):
            raise TypeError("system must be a string")
        if not isinstance(self.prompt, str):
            raise TypeError("prompt must be a string")

        if self.json_schema is not None:
            if not isinstance(self.json_schema, dict):
                raise TypeError("json_schema must be a dictionary or None")
            object.__setattr__(self, "json_schema", copy.deepcopy(self.json_schema))

        try:
            temperature = float(self.temperature)
        except (TypeError, ValueError) as exc:
            raise ValueError("temperature must be numeric") from exc
        if not math.isfinite(temperature):
            raise ValueError("temperature must be finite")
        # Ollama accepts non-negative temperatures; cap the shared contract at
        # 2.0 to avoid accidental provider-specific extremes.
        object.__setattr__(self, "temperature", max(0.0, min(2.0, temperature)))

        try:
            max_output_tokens = int(self.max_output_tokens)
        except (TypeError, ValueError) as exc:
            raise ValueError("max_output_tokens must be an integer") from exc
        object.__setattr__(
            self,
            "max_output_tokens",
            max(1, min(32768, max_output_tokens)),
        )


@dataclass(frozen=True)
class LLMResponse:
    """Normalized text and telemetry returned by a provider."""

    text: str
    model: str
    usage: dict[str, int]
    raw: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must not be empty")
        if not isinstance(self.usage, dict):
            raise TypeError("usage must be a dictionary")
        if not isinstance(self.raw, dict):
            raise TypeError("raw must be a dictionary")
        object.__setattr__(self, "usage", copy.deepcopy(self.usage))
        object.__setattr__(self, "raw", copy.deepcopy(self.raw))


@runtime_checkable
class LLMProvider(Protocol):
    """The interface consumed by ``GhostBrain`` and application services."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one non-streaming response."""

    def health(self) -> dict[str, Any]:
        """Return provider availability and installed-model information."""
