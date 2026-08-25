import json
from types import SimpleNamespace

from ghost_protocol.application.llm_provider import LLMResponse
from ghost_protocol.brain import GhostBrain


class _FakeProvider:
    def __init__(self):
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        payloads = {
            "suggest_topic": {"topic": "오늘 분위기 왜 이럼"},
            "generate_post": {
                "title": "오늘 분위기 왜 이럼",
                "content": "새로 올라온 글 흐름을 보니 다들 같은 부분에서 멈칫하는 느낌이다",
                "target_comments": [],
            },
            "judge_post": {"pass": True},
        }
        payload = payloads.get(request.task, {
            "hot_topics": ["테스트 소재"],
            "sentiment": "장난",
            "memes": [],
            "summary": "테스트 요약",
            "ai_analysis": "테스트 분석",
            "generation_guidance": "테스트 지시",
        })
        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            model="qwen2.5:3b",
            usage={"eval_count": 1},
            raw={"done_reason": "stop"},
        )


def test_ghost_brain_injects_provider_and_keeps_public_methods(monkeypatch):
    provider = _FakeProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:3b")
    monkeypatch.setattr(
        brain,
        "_get_current_context",
        lambda gallery_id, hours=1: [{"title": "새 글 흐름"}],
    )
    monkeypatch.setattr(brain, "_get_style_examples", lambda gallery_id, n=3: [])

    topic = brain.suggest_topic("test_gallery")
    post = brain.generate_post("테스트 주제", "test_gallery", context_hours=0)
    judged = brain.judge_post("제목", "본문", gallery_id="test_gallery")

    assert topic == "오늘 분위기 왜 이럼"
    assert post["title"] == "오늘 분위기 왜 이럼?"
    assert judged == {"pass": True}
    assert [request.task for request in provider.requests] == [
        "suggest_topic",
        "generate_post",
        "judge_post",
    ]
    assert provider.requests[0].json_schema["required"] == ["topic"]
    assert provider.requests[1].json_schema is None


def test_ghost_brain_default_provider_is_loopback_ollama(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SEC", "90")
    monkeypatch.setenv("OLLAMA_NUM_CTX", "2048")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "5m")

    brain = GhostBrain()

    assert brain.provider.base_url == "http://127.0.0.1:11434"
    assert brain.provider.model == "qwen2.5:3b"
    assert brain.provider.timeout_seconds == 90.0
    assert brain.provider.num_ctx == 2048
    assert brain.provider.keep_alive == "5m"
