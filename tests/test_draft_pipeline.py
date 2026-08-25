from ghost_protocol.application.draft_pipeline import (
    build_draft_card,
    build_source_brief,
    validate_draft,
)


TOPIC = """[G: 갤러리 본래 주제]
- 분야: 우주·천문
- 이번 초점: 허블 사진에 보이는 토성의 고리와 행성 그림자
- 입력에 적힌 사실: 사진 안에 토성의 고리와 어두운 행성 그림자가 함께 보임
"""


def test_source_brief_keeps_only_grounded_focus_and_anchors():
    brief = build_source_brief(TOPIC, "universe", "G")

    assert brief.slot == "G"
    assert "토성의 고리" in brief.focus
    assert brief.facts == ("사진 안에 토성의 고리와 어두운 행성 그림자가 함께 보임",)
    assert {"토성", "고리", "행성", "그림자"}.issubset(set(brief.anchors))
    assert "몇 년" not in brief.writer_prompt if hasattr(brief, "writer_prompt") else True


def test_draft_card_is_compact_and_disables_comments_without_targets():
    brief = build_source_brief(TOPIC, "universe", "G")
    card = build_draft_card(
        brief,
        tone="scene_noticer",
        length="보통 (3~4문장)",
        tone_description="장면 하나를 붙여 짧게 반응한다.",
        persona_profile={
            "vocab_style": "구체 장면 중심",
            "good_moves": ["사진 속 한 장면을 짚는다"],
            "bad_moves": ["설명문으로 늘인다"],
            "never_say": ["입력 밖 수치"],
        },
        has_comment_targets=False,
    )

    prompt = card.writer_prompt()
    assert len(prompt) < 2400
    assert "사진 안에 토성의 고리와 어두운 행성 그림자가 함께 보임" in prompt
    assert "target_comments는 반드시 빈 배열" in prompt
    assert "입력에 없는 수치" in prompt
    assert "scene_noticer" not in prompt


def test_draft_card_preserves_full_persona_contract():
    brief = build_source_brief(TOPIC, "universe", "G")
    card = build_draft_card(
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
    )

    assert card.persona_domains == ("구체 장면", "시청·관측 체감")
    assert card.vocab_style == "사진에서 보인 장면을 짧게 짚는다"
    prompt = card.writer_prompt()
    assert "관심 장면: 구체 장면, 시청·관측 체감" in prompt
    assert "어휘 스타일: 사진에서 보인 장면을 짧게 짚는다" in prompt
    assert "가짜 경험" in prompt


def test_validator_rejects_anchor_drift_and_comment_pollution():
    brief = build_source_brief(TOPIC, "universe", "G")
    card = build_draft_card(
        brief,
        tone="neutral",
        length="짧게 (1~2문장)",
        tone_description="바로 반응한다.",
        persona_profile={},
        has_comment_targets=False,
    )

    reasons = validate_draft(
        card,
        title="오늘 날씨",
        content="새로운 소식이네",
        target_comments=[{"post_no": "1", "comment": "좋다"}],
    )

    assert "anchor_missing" in reasons
    assert "comments_without_targets" in reasons


def test_validator_allows_grounded_draft_with_real_targets():
    brief = build_source_brief(TOPIC, "universe", "G")
    card = build_draft_card(
        brief,
        tone="neutral",
        length="짧게 (1~2문장)",
        tone_description="바로 반응한다.",
        persona_profile={},
        has_comment_targets=True,
    )

    assert validate_draft(
        card,
        title="토성의 고리와 그림자",
        content="고리와 그림자가 같이 보이네",
        target_comments=[{"post_no": "1", "comment": "같이 보이네"}],
    ) == ()
