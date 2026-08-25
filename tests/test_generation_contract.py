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
    assert request.json_schema is None
    assert request.temperature == 0.4
    assert "장면 하나를 짧게 붙인다" in request.prompt or "구체 장면" in request.prompt
    assert "[반복 방지]" in request.prompt
    assert "[출력 전 점검]" in request.prompt
    assert "입력에 없는 수치·변화·비교" in request.prompt


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
