import json

from ghost_protocol.application.llm_provider import LLMResponse
from ghost_protocol.brain import GhostBrain


class _WriterProvider:
    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return LLMResponse(
            text=json.dumps(
                {
                    "title": "먼지 원반 사진 한 장",
                    "content": "고리처럼 보이는 구조가 먼저 눈에 들어오네",
                    "target_comments": [],
                },
                ensure_ascii=False,
            ),
            model="qwen2.5:7b",
            usage={"eval_count": 1},
            raw={"done_reason": "stop"},
        )


def test_generate_post_compiles_prompt_and_injects_expected_slot(monkeypatch):
    provider = _WriterProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:7b")
    monkeypatch.setattr(brain, "_get_style_examples", lambda gallery_id, n=3: [])

    result = brain.generate_post(
        """[G: 갤러리 본래 주제]
- 분야: 우주·천문
- 이번 초점: 먼지 원반 사진에서 보이는 구조
""",
        "universe",
        tone="scene_noticer",
        context_hours=None,
        length="짧게 (1~2문장)",
        expected_slot="G",
    )

    request = provider.requests[0]
    assert result["title"] == "먼지 원반 사진 한 장"
    assert result["_thought_process"]["slot_used"] == "G"
    assert result["_thought_process"]["pipeline"] == "structured_card"
    assert request.json_schema is None
    assert request.temperature == 0.4
    assert "[작문 카드]" in request.prompt
    assert "확인된 사실" in request.prompt
    assert "입력에 없는 수치" in request.prompt
    assert "target_comments는 반드시 빈 배열" in request.prompt


def test_generate_post_can_opt_into_detailed_json_schema(monkeypatch):
    provider = _WriterProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:7b")
    monkeypatch.setenv("LLM_JSON_SCHEMA_MODE", "1")
    monkeypatch.setattr(brain, "_get_style_examples", lambda gallery_id, n=3: [])

    brain.generate_post(
        "[G: 갤러리 본래 주제]\n- 분야: 우주·천문\n- 이번 초점: 먼지 원반 사진",
        "universe",
        tone="scene_noticer",
        context_hours=None,
        length="짧게 (1~2문장)",
        expected_slot="G",
    )

    assert provider.requests[0].json_schema["required"] == [
        "title",
        "content",
        "target_comments",
    ]


def test_registered_purpose_does_not_receive_unrelated_default_fewshot():
    brain = GhostBrain(provider=_WriterProvider(), model_name="qwen2.5:7b")

    context = brain._get_gallery_context("universe")

    assert context == ""


class _CardRetryProvider:
    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if request.task == "generate_post":
            payload = {
                "title": "새 소식",
                "content": "그냥 올라왔네",
                "target_comments": [{"post_no": "1", "comment": "좋다"}],
            }
        else:
            payload = {
                "title": "먼지 원반 사진",
                "content": "먼지 원반의 빈틈이 먼저 보이네",
                "target_comments": [],
            }
        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            model="qwen2.5:3b",
            usage={"eval_count": 1},
            raw={"done_reason": "stop"},
        )


def test_structured_pipeline_retries_only_when_card_validation_fails():
    provider = _CardRetryProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:3b")

    result = brain.generate_post(
        "[G: 갤러리 본래 주제]\n- 이번 초점: 먼지 원반 사진에서 보이는 빈틈",
        "universe",
        tone="neutral",
        context_hours=None,
        length="짧게 (1~2문장)",
        expected_slot="G",
    )

    assert result["title"] == "먼지 원반 사진"
    assert result["target_comments"] == []
    assert result["_thought_process"]["pipeline"] == "structured_card_retry"
    assert [request.task for request in provider.requests] == [
        "generate_post",
        "generate_post_compact",
    ]
