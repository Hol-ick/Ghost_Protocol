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
    monkeypatch.setenv("LLM_DRAFT_PIPELINE_MODE", "legacy")
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


def test_analyze_trend_rejects_extra_summary_slots(monkeypatch):
    class ExtraSlotProvider:
        def generate(self, request):
            return LLMResponse(
                text=json.dumps(
                    {
                        "hot_topics": ["악력", "판매"],
                        "sentiment": "장난",
                        "memes": ["좋은 아침"],
                        "topic_slots": ["악력", "판매", "방문", "패치"],
                        "ai_analysis": "악력과 판매글, 방문기가 섞인 흐름이다.",
                        "generation_guidance": "실제 제목의 구체 대상을 하나만 골라 짧게 참여한다.",
                    },
                    ensure_ascii=False,
                ),
                model="qwen2.5:3b",
                usage={"eval_count": 1},
                raw={"done_reason": "stop"},
            )

    monkeypatch.setenv("LLM_TREND_CACHE_TTL_SEC", "0")
    brain = GhostBrain(provider=ExtraSlotProvider(), model_name="qwen2.5:3b")

    result = brain.analyze_trend(
        {
            "gallery_id": "universe",
            "titles": ["악력 91kg", "망치 팝니다", "다케시타 도리"],
            "comments": ["좋은 아침"],
        }
    )

    assert result["_parse_error"] is True
    assert result["_failure_reason"] == "invalid_trend_payload"


def test_analyze_trend_uses_label_free_compact_contract_for_3b(monkeypatch):
    class CompactProvider:
        def __init__(self):
            self.request = None

        def generate(self, request):
            self.request = request
            return LLMResponse(
                text=json.dumps(
                    {
                        "hot_topics": ["망원경", "목성 줄무늬"],
                        "sentiment": "기대",
                        "memes": [],
                        "topic_slots": ["망원경 가장자리", "목성 줄무늬", "사진 후보정"],
                        "ai_analysis": "망원경 가장자리와 목성 줄무늬 사진을 두고 촬영 결과와 후보정 차이를 가볍게 비교하는 반응이 이어진다.",
                        "generation_guidance": "제목에 나온 장비나 장면 하나만 골라 짧게 반응한다. 없는 사건이나 특정 인물 이야기는 만들지 않는다.",
                    },
                    ensure_ascii=False,
                ),
                model="qwen2.5:3b",
                usage={"eval_count": 1},
                raw={"done_reason": "stop"},
            )

    monkeypatch.setenv("LLM_TREND_CACHE_TTL_SEC", "0")
    provider = CompactProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:3b")

    result = brain.analyze_trend(
        {
            "gallery_id": "universe",
            "titles": ["목성 줄무늬 잘 보이네", "망원경 가장자리 찍힘"],
            "comments": ["후보정 차이인가"],
        }
    )

    assert result.get("_parse_error") is not True
    assert result["summary"] == "[A: 망원경 가장자리] / [B: 목성 줄무늬] / [C: 사진 후보정]"
    assert not result["ai_analysis"].startswith("ID 기반 기본축")
    assert provider.request is not None
    assert "[A:" not in provider.request.prompt
    assert "topic_slots" in provider.request.json_schema["properties"]
    assert "summary" not in provider.request.json_schema["properties"]


def test_analyze_trend_rejects_length_terminated_response(monkeypatch):
    class TruncatedProvider:
        def generate(self, request):
            return LLMResponse(
                text=json.dumps(
                    {
                        "hot_topics": ["악력", "판매"],
                        "sentiment": "장난",
                        "memes": ["좋은 아침"],
                        "summary": "[A: 악력] / [B: 판매] / [C: 방문]",
                        "ai_analysis": "악력과 판매글, 방문기가 섞인 흐름이다.",
                        "generation_guidance": "실제 제목의 구체 대상을 하나만 골라 짧게 참여한다.",
                    },
                    ensure_ascii=False,
                ),
                model="qwen2.5:3b",
                usage={"eval_count": 1},
                raw={"done_reason": "length"},
            )

    monkeypatch.setenv("LLM_TREND_CACHE_TTL_SEC", "0")
    brain = GhostBrain(provider=TruncatedProvider(), model_name="qwen2.5:3b")

    result = brain.analyze_trend(
        {"gallery_id": "universe", "titles": ["악력 91kg"], "comments": ["좋은 아침"]}
    )

    assert result["_parse_error"] is True
    assert result["_failure_reason"] == "truncated_response"
