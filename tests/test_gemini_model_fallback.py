from types import SimpleNamespace

import pytest

from ghost_protocol.brain import GhostBrain
from ghost_protocol.application import gemini_budget


class _FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        model = kwargs["model"]
        self.calls.append(model)
        if model == "primary-model":
            raise Exception("429 RESOURCE_EXHAUSTED quota exceeded")
        return SimpleNamespace(text='{"ok": true}')


def test_generate_content_paced_falls_back_after_rate_limit(monkeypatch):
    monkeypatch.setenv("GEMINI_CALL_MIN_INTERVAL_SEC", "0")
    monkeypatch.setenv("GEMINI_CALL_JITTER_SEC", "0")
    monkeypatch.setenv("GEMINI_MAX_CALLS_PER_RUN", "0")
    gemini_budget.reset_run("test-fallback")

    fake_models = _FakeModels()
    brain = GhostBrain.__new__(GhostBrain)
    brain._client = SimpleNamespace(models=fake_models)
    brain.model_name = "primary-model"
    brain.fallback_model_names = ("fallback-model",)

    result = brain._generate_content_paced(
        label="unit-test",
        model="primary-model",
        contents="hello",
    )

    assert result.text == '{"ok": true}'
    assert fake_models.calls == ["primary-model", "fallback-model"]


def test_generate_content_paced_stops_on_billing_credit_error(monkeypatch):
    monkeypatch.setenv("GEMINI_CALL_MIN_INTERVAL_SEC", "0")
    monkeypatch.setenv("GEMINI_CALL_JITTER_SEC", "0")
    monkeypatch.setenv("GEMINI_MAX_CALLS_PER_RUN", "0")
    gemini_budget.reset_run("test-billing")

    class _BillingModels:
        def __init__(self):
            self.calls = []

        def generate_content(self, **kwargs):
            self.calls.append(kwargs["model"])
            raise Exception("429 Your prepayment credits are depleted. Please manage billing.")

    fake_models = _BillingModels()
    brain = GhostBrain.__new__(GhostBrain)
    brain._client = SimpleNamespace(models=fake_models)
    brain.model_name = "primary-model"
    brain.fallback_model_names = ("fallback-model",)

    with pytest.raises(gemini_budget.GeminiBillingError):
        brain._generate_content_paced(
            label="unit-test",
            model="primary-model",
            contents="hello",
        )

    assert fake_models.calls == ["primary-model"]
