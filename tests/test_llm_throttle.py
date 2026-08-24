from ghost_protocol.application import llm_throttle


def test_normalize_seconds_clamps_invalid_and_bounds():
    assert llm_throttle.normalize_seconds("bad", default=2.0, upper=10.0) == 2.0
    assert llm_throttle.normalize_seconds("-3", default=2.0, upper=10.0) == 0.0
    assert llm_throttle.normalize_seconds("99", default=2.0, upper=10.0) == 10.0


def test_configured_values_read_environment(monkeypatch):
    monkeypatch.setenv("LLM_CALL_MIN_INTERVAL_SEC", "3.5")
    monkeypatch.setenv("LLM_CALL_JITTER_SEC", "1.25")

    assert llm_throttle.configured_min_interval() == 3.5
    assert llm_throttle.configured_jitter() == 1.25


def test_wait_before_call_can_be_disabled(monkeypatch):
    monkeypatch.setenv("LLM_CALL_MIN_INTERVAL_SEC", "0")
    monkeypatch.setenv("LLM_CALL_JITTER_SEC", "0")

    waited = llm_throttle.wait_before_call("test")

    assert waited == 0
