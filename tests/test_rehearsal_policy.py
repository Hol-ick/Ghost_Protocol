from ghost_protocol.domain import rehearsal_policy


def test_soft_cooldown_block_is_not_a_hard_ban():
    block = rehearsal_policy.soft_cooldown_prompt_block(
        topics=["목성 중력 행성 공장"],
        title_keywords=["목성"],
        starts=["이거"],
    )

    assert "[리허설 소프트 쿨다운]" in block
    assert "금지가 아니라 반복 피로 신호" in block
    assert "사용해도 된다" in block
    assert "목성 중력 행성 공장" in block


def test_slot_drift_is_allowed_only_for_rehearsal_diagnostics():
    assert rehearsal_policy.allow_rehearsal_slot_drift(
        expected_slot="G",
        observed_slot="R",
        title="목성 먼지대 사진",
        content="도넛 모양으로 보임",
    )
    assert not rehearsal_policy.allow_rehearsal_slot_drift(
        expected_slot="G",
        observed_slot="G",
        title="목성 먼지대 사진",
        content="도넛 모양으로 보임",
    )
    assert not rehearsal_policy.allow_rehearsal_slot_drift(
        expected_slot="",
        observed_slot="R",
    )


def test_failure_pattern_labels_hide_candidate_wording():
    assert rehearsal_policy.failure_pattern_label("지정 슬롯 R 대신 A을 사용했습니다.") == "slot_drift"
    assert rehearsal_policy.failure_pattern_label("순수 메타 평론이다.") == "meta_reaction"
    assert rehearsal_policy.failure_pattern_label("안전 필터: protected_group_direct") == "safety_guard"


def test_strong_safety_reason_is_separate_from_quality_failure():
    assert rehearsal_policy.is_strong_safety_reason("성희롱 표현이 포함됨")
    assert not rehearsal_policy.is_strong_safety_reason("자연스러움 정책 위반")
