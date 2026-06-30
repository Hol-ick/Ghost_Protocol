import json
from types import SimpleNamespace

from ghost_protocol.application import gemini_budget, trend_cache
from ghost_protocol.brain import GhostBrain


def test_trend_cache_round_trip_uses_ttl(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_TREND_CACHE_TTL_SEC", "3600")
    monkeypatch.setattr(trend_cache, "_CACHE_PATH", tmp_path / "trend_cache.json")

    key = trend_cache.build_key(
        gallery_id="universe",
        titles=["목성 사진"],
        comments=["크기 차이 신기함"],
        prompt_template="prompt-v1",
    )

    trend_cache.set(key, {"hot_topics": ["목성"], "sentiment": "장난"})

    cached = trend_cache.get(key)

    assert cached == {"hot_topics": ["목성"], "sentiment": "장난"}


def test_analyze_trend_reuses_cached_gemini_result(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_TREND_CACHE_TTL_SEC", "3600")
    monkeypatch.setenv("GEMINI_MAX_CALLS_PER_RUN", "0")
    monkeypatch.setattr(trend_cache, "_CACHE_PATH", tmp_path / "trend_cache.json")
    gemini_budget.reset_run("trend-cache-test")

    calls = {"count": 0}

    def fake_generate_content(*, label, **kwargs):
        calls["count"] += 1
        payload = {
            "hot_topics": ["목성 중력", "행성 먼지"],
            "sentiment": "장난",
            "memes": ["ㄷㄷ"],
            "summary": "[A: 목성 중력] / [B: 먼지 원반] / [C: 관측 궁금증]",
            "ai_analysis": "목성 중력과 먼지 원반 이야기가 반복되고 있습니다. 행성 형성 과정을 두고 가볍게 놀라는 반응이 보입니다.",
            "generation_guidance": "목성 중력과 행성 형성 소재를 중심으로 짧게 반응합니다.",
        }
        return SimpleNamespace(
            text=json.dumps(payload, ensure_ascii=False),
            candidates=[SimpleNamespace(finish_reason="FinishReason.STOP")],
        )

    brain = GhostBrain.__new__(GhostBrain)
    brain._generate_content_paced = fake_generate_content

    raw_data = {
        "gallery_id": "universe",
        "titles": ["목성 중력으로 행성 만드는 거 가능함?", "먼지 원반 사진 신기하네"],
        "comments": ["저게 모이면 행성 되는 건가"],
        "authors": ["ㅇㅇ", "ㅇㅇ"],
    }

    first = brain.analyze_trend(raw_data)
    second = brain.analyze_trend(raw_data)

    assert calls["count"] == 1
    assert first["hot_topics"]
    assert second["_cache_hit"] is True
