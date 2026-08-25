from ghost_protocol.application.draft_pipeline import build_draft_card, build_source_brief
from ghost_protocol.application.draft_quality import grounded_fallback, review_draft


TOPIC = """[G: 갤러리 본래 주제]
- 분야: 우주·천문
- 이번 초점: 허블 사진에 보이는 토성의 고리와 행성 그림자
- 입력에 적힌 사실: 사진 안에 토성의 고리와 어두운 행성 그림자가 함께 보임
"""


def _card(*, has_comment_targets: bool = False):
    brief = build_source_brief(TOPIC, "universe", "G")
    return build_draft_card(
        brief,
        tone="scene_noticer",
        length="보통 (3~4문장)",
        tone_description="장면 하나를 붙여 짧게 반응한다.",
        persona_profile={
            "domain_affinity": ["구체 장면", "시청·관측 체감"],
            "vocab_style": "사진에서 보인 장면을 짧게 짚는다",
            "good_moves": ["사진 속 한 장면을 짚는다"],
            "bad_moves": ["설명문으로 늘인다"],
            "never_say": ["입력 밖 수치", "가짜 경험"],
        },
        has_comment_targets=has_comment_targets,
    )


def test_review_accepts_grounded_complete_sentence():
    review = review_draft(
        _card(),
        "토성의 고리와 그림자가 같이 보이네",
        "허블 사진에서 토성의 고리와 어두운 그림자가 함께 보이네.",
        [],
    )

    assert review.accepted is True
    assert review.issues == ()
    assert review.metrics["anchor_hits"] >= 2


def test_review_rejects_unsupported_numbers_and_causes():
    review = review_draft(
        _card(),
        "토성 그림자 300만 킬로미터",
        "허블 사진에서 그림자가 300만 킬로미터 길고, 토성의 회전 속도 때문에 생긴 현상이야.",
        [],
    )

    assert review.accepted is False
    assert "unsupported_claim" in review.issues


def test_review_rejects_prompt_leak_and_incomplete_sentence():
    review = review_draft(
        _card(),
        "하나",
        "[페르소나 심화] 보이",
        [],
    )

    assert review.accepted is False
    assert "prompt_leak" in review.issues
    assert "incomplete_sentence" in review.issues
    assert "short_sentence" in review.issues


def test_review_rejects_fact_contradiction():
    review = review_draft(
        _card(),
        "토성 고리는 안 보이네",
        "허블 사진에는 토성의 고리와 그림자가 함께 보이지 않아.",
        [],
    )

    assert review.accepted is False
    assert "fact_contradiction" in review.issues


def test_review_rejects_unsupported_temporal_or_visual_claims():
    review = review_draft(
        _card(),
        "토성이 다시 빛나나?",
        "이번 허블 사진에서 토성의 고리가 잘 빛나고 다음에는 다른 행성이 추가될까?",
        [],
    )

    assert review.accepted is False
    assert "unsupported_claim" in review.issues


def test_review_rejects_comments_without_real_targets():
    review = review_draft(
        _card(),
        "토성의 고리와 그림자",
        "둘이 같이 보이네.",
        [{"post_no": "1", "comment": "좋다"}],
    )

    assert review.accepted is False
    assert "comments_without_targets" in review.issues


def test_review_builds_targeted_repair_prompt():
    review = review_draft(
        _card(),
        "토성의 고리",
        "허블 사진에서 토성 고리 보이",
        [],
    )

    assert review.repair_prompt
    assert "incomplete_sentence" in review.repair_prompt
    assert "확인된 사실" in review.repair_prompt


def test_grounded_fallback_is_complete_and_persona_safe():
    card = _card()
    title, content = grounded_fallback(card)
    review = review_draft(card, title, content, [])

    assert title == "허블 토성 고리"
    assert "토성의 고리" in content
    assert review.accepted is True
    assert "unsupported_claim" not in review.issues
