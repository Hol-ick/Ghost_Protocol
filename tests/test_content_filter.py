from ghost_protocol.content_filter import (
    classify_noise_text,
    extract_user_drama_terms,
    filter_noise_strings,
    sanitize_analysis_keywords,
    sanitize_sensitive_target_comments,
    sanitize_user_drama_text,
    sensitive_generation_violations,
)


def test_auto_hunting_is_filtered_as_noise():
    decision = classify_noise_text("오토사냥 프로그램 무료 공유 문의")

    assert decision.is_noise
    assert "auto_hunt" in decision.reasons


def test_payment_promo_variant_is_filtered_as_noise():
    decision = classify_noise_text("리버p.a.y 충전 문의")

    assert decision.is_noise
    assert "payment_promo" in decision.reasons


def test_ordinary_discussion_is_not_filtered():
    decision = classify_noise_text("평평지구론 근거 물어보면 왜 맨날 말이 바뀜")

    assert not decision.is_noise


def test_filter_noise_strings_returns_clean_items_and_stats():
    clean, stats = filter_noise_strings([
        "달착륙 조작이라는 글 또 올라왔네",
        "계정 판매 문의 텔레그램",
        "오토사냥 매크로 다운 링크",
    ])

    assert clean == ["달착륙 조작이라는 글 또 올라왔네"]
    assert stats["removed_count"] == 2
    assert len(stats["removed_samples"]) == 2


def test_sensitive_generation_rejects_direct_group_reference():
    hits = sensitive_generation_violations(
        "백인 글은 또 왜 이렇게 많음",
        topic="특정 인종 혐오성 일반화",
    )

    assert "protected_group_direct" in hits


def test_sensitive_generation_rejects_dehumanizing_metaphor():
    hits = sensitive_generation_violations(
        "기생충 드립 너무 과한 거 아님",
        topic="특정 인종 비하",
    )

    assert "dehumanizing_metaphor" in hits


def test_sensitive_generation_allows_abstract_community_reaction():
    hits = sensitive_generation_violations(
        "혐오떡밥 선 넘는 거 같음",
        topic="특정 인종 비하",
    )

    assert hits == []


def test_sensitive_comment_sanitizer_drops_risky_comments():
    clean = sanitize_sensitive_target_comments(
        [
            {"post_no": "1", "comment": "이건 너무 일반화 아님"},
            {"post_no": "2", "comment": "똥양인 비유는 진짜 역겹다"},
        ],
        topic="특정 인종 비하",
    )

    assert clean == [{"post_no": "1", "comment": "이건 너무 일반화 아님"}]


def test_analysis_keywords_drop_sensitive_and_filler_terms():
    clean = sanitize_analysis_keywords(
        ["똥양인", "동양인", "오늘", "혐오성 일반화", "달착륙 음모론"],
        source_text="특정 인종 비하와 혐오성 일반화",
    )

    assert clean == ["혐오성 일반화", "달착륙 음모론"]


def test_sexualized_generation_rejects_raw_source_phrase_and_labels():
    topic = "특정 여성 인물에 대한 성희롱 및 관계 추측. 유나누나, 파트너이자 가족 표현 반복"

    hits = sensitive_generation_violations(
        "파트너이자 가족 드립은 좀 너무 간 거 아니냐",
        topic=topic,
    )
    assert "sexualized_source_phrase" in hits

    hits = sensitive_generation_violations(
        "유나누나 얘기는 왜 계속 나옴",
        topic=topic,
    )
    assert "sexualized_person_label" in hits


def test_sexualized_analysis_keywords_drop_raw_terms():
    clean = sanitize_analysis_keywords(
        ["유나누나", "벅지", "성희롱성 말투", "관계 추측"],
        source_text="특정 여성 인물에 대한 성희롱 및 관계 추측. 유나누나 벅지 언급",
    )

    assert clean == ["성희롱성 말투", "관계 추측"]


def test_user_drama_terms_are_extracted_from_nickname_context():
    terms = extract_user_drama_terms("특정 유저 '딸근이'의 로진짓과 뒷담 논란")

    assert terms == ["딸근이"]


def test_user_drama_terms_extract_parenthetical_person_and_related_complaint():
    assert extract_user_drama_terms("특정 인물(재승)에 대한 불만") == ["재승"]
    assert extract_user_drama_terms("재승 관련 불만") == ["재승"]


def test_user_drama_generation_rejects_reused_nickname():
    hits = sensitive_generation_violations(
        "딸근이 얘는 왜 이럼",
        topic="특정 유저 '딸근이'의 로진짓과 뒷담 논란",
    )

    assert "named_user_drama" in hits


def test_public_issue_is_not_misread_as_named_user_drama():
    hits = sensitive_generation_violations(
        "선관위 투표지 오류는 재확인이 필요해 보임",
        topic=(
            "특정 유저 관련 논란도 일부 있음\n"
            "[A: 선관위 투표지 오류 논란] / [B: 빚투 급증] / [C: 기본소득]"
        ),
    )

    assert "named_user_drama" not in hits


def test_regional_slur_is_rejected_as_hard_hate():
    hits = sensitive_generation_violations(
        "홍어란 말을 왜 싫어함",
        topic="홍어란 말이 반복되는 저격성 글",
    )

    assert "hard_hate_term" in hits


def test_user_drama_text_sanitizes_nickname():
    text = sanitize_user_drama_text(
        "딸근이 로진짓 및 뒷담 논란",
        source_text="특정 유저 '딸근이'의 행동 논란",
    )

    assert text == "특정 유저 로진짓 및 뒷담 논란"
