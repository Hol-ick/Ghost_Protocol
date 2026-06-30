from ghost_protocol.domain import gallery_purpose


def test_universe_profile_has_space_purpose():
    profile = gallery_purpose.get_profile("universe")

    assert profile["topic_label"] == "우주·천문"
    assert profile["inferred_key"] == "astronomy"
    assert gallery_purpose.text_matches("universe", "평면설이면 중력은 뭐가 됨?", "")


def test_gallery_purpose_is_inferred_from_id_family_not_exact_id():
    astronomy = gallery_purpose.get_profile("universe_archive")
    baseball = gallery_purpose.get_profile("baseball_new99")

    assert astronomy["inferred_key"] == "astronomy"
    assert baseball["inferred_key"] == "baseball"
    assert gallery_purpose.get_profile("unrelated_board") == {}


def test_purpose_wave_is_exactly_one_mid_batch():
    waves = [
        index
        for index in range(1, 6)
        if gallery_purpose.is_purpose_wave("universe", index, 5)
    ]

    assert waves == [3]


def test_guidance_uses_matching_source_examples():
    block = gallery_purpose.guidance_block(
        "universe",
        [
            {"title": "빚투 계속 느는 중인가", "content": ""},
            {"title": "평면설 주장에 그럼 중력은 뭐임", "content": ""},
        ],
    )

    assert "평면설 주장에 그럼 중력은 뭐임" in block
    assert "빚투 계속" not in block


def test_guidance_has_configured_fallback_when_sources_do_not_match():
    block = gallery_purpose.guidance_block(
        "universe",
        [{"title": "1000개 투표지 오류", "content": "선거 관련 글"}],
    )

    assert "새 사건을 꾸며내지 말고" in block
    assert "달·별·행성" in block
    assert "ID는 분야 선택에만 사용" in block


def test_identity_context_is_inferred_from_gallery_id():
    context = gallery_purpose.analysis_context("universe_archive")

    assert "universe_archive" in context
    assert "우주·천문" in context
    assert "현재 유행의 증거가 아니라" in context


def test_generation_instruction_uses_user_facing_identity_wording():
    instruction = gallery_purpose.generation_instruction("universe")

    assert "등록된 상시 분야" in instruction
    assert "ID/이름 토큰" not in instruction


def test_strip_identity_echo_removes_repeated_intro():
    cleaned = gallery_purpose.strip_identity_echo(
        "universe 갤러리의 기본 분야는 우주·천문입니다. 현재 수집분에서는 선관위 사과 시점이 반복됩니다.",
        "universe",
    )

    assert "기본 분야" not in cleaned
    assert cleaned.startswith("선관위 사과 시점")


def test_strip_identity_echo_removes_deterministic_prefix_echo():
    cleaned = gallery_purpose.strip_identity_echo(
        "ID 기반 기본축은 우주·천문입니다. 현재 수집분에서는 목성 중력 활용 글이 이어집니다.",
        "universe",
    )

    assert "ID 기반 기본축" not in cleaned
    assert cleaned.startswith("목성 중력 활용")


def test_unknown_gallery_has_no_forced_identity():
    assert gallery_purpose.identity_metadata("unrelated_board") == {}
    assert "등록된 기본 분야 없음" in gallery_purpose.analysis_context(
        "unrelated_board"
    )
