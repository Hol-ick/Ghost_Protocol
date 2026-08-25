import json

from ghost_protocol.application.draft_generation import (
    invalidate_candidate_state,
)
from ghost_protocol.application.llm_provider import LLMResponse
from ghost_protocol.brain import GhostBrain


def test_terminal_parse_failure_clears_previous_candidate():
    title, content, comments = invalidate_candidate_state(
        "이전 제목",
        "이전 본문",
        [{"post_no": "1", "comment": "이전 댓글"}],
    )

    assert title is None
    assert content == ""
    assert comments == []


class _CompactProvider:
    def __init__(self):
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return LLMResponse(
            text=json.dumps(
                {
                    "title": "망원경 해상도 차이",
                    "content": "행성 표면을 볼 때 망원경 해상도가 체감 차이를 만들더라",
                    "target_comments": [],
                },
                ensure_ascii=False,
            ),
            model="qwen2.5:3b",
            usage={"eval_count": 18},
            raw={"done_reason": "stop"},
        )


def test_compact_generation_uses_short_local_contract(monkeypatch):
    provider = _CompactProvider()
    brain = GhostBrain(provider=provider, model_name="qwen2.5:3b")

    result = brain.generate_post_compact(
        topic="현재 분석은 특정 논란이지만 게시판 기본축은 우주·천문이다.",
        gallery_id="universe",
        tone="neutral",
        length="짧게 (1~2문장)",
        focus="달·별·행성·중력·관측 장비처럼 오래된 우주 떡밥의 구체 지점",
    )

    assert result["title"] == "망원경 해상도 차이"
    assert result["target_comments"] == []
    assert provider.requests[0].task == "generate_post_compact"
    assert len(provider.requests[0].prompt) < 1800
