from ghost_protocol.domain import naturalness


def test_forced_topic_switch_patterns_are_policy_driven():
    assert naturalness.has_forced_topic_switch("선거 얘기 왜 이렇게 많냐", "")
    assert not naturalness.has_forced_topic_switch("환율 1400이면 또 체감 오겠네", "")


def test_newbie_definition_questions_are_rejected():
    assert naturalness.has_newbie_definition_question("야대기 무슨 뜻임", "")
    assert not naturalness.has_newbie_definition_question("야대기 거기에 붙이는 게 맞냐", "")


def test_concrete_hooks_allow_specific_reactions():
    assert naturalness.has_concrete_hook("압승 이 단어 쓰는 게 맞나", "")
    assert not naturalness.has_concrete_hook("오늘도 얘기 많네", "")


def test_generation_policy_block_is_loaded_from_json():
    block = naturalness.generation_policy_block()

    assert "[자연스러움 정책]" in block
    assert "기존 화제를 밀어내는 빈도 불평" in block


def test_review_package_meta_failures_are_rejected():
    assert naturalness.has_hard_meta_reaction("총선 출구조사 또 저러네", "")
    assert naturalness.has_hard_meta_reaction("출구조사 얘기 진짜 언제까지 보냐", "")
    assert naturalness.has_forced_topic_switch("20대 남성 얘기 또 나온 거 왜임", "")
    assert naturalness.has_generic_meta_reaction(
        "세대별 그거 이제 그만 볼 때도 됐는데",
        "맨날 똑같은 패턴인데 뭐 굳이 계속 보냐",
    )


def test_specific_result_reaction_is_not_meta_failure():
    assert not naturalness.has_hard_meta_reaction(
        "출구조사 최종까지 봐야 되는 거 아님",
        "초반 숫자만 보고 압승이라고 박는 건 좀 빠른 듯",
    )


def test_late_phase_moves_to_underused_axis_without_announcing_switch():
    text = naturalness.phase_instruction(0.8)

    assert "적게 다룬 B/C" in text
    assert "화제전환을 선언하지 말고" in text


def test_review_package_moderator_phrasing_is_rejected():
    failures = [
        ("이번 총선 결과 이렇게까지 된거임?", ""),
        ("출구조사 결과 이거 다들 납득하는 분위기임", ""),
        ("부정선거 얘기는 항상 이렇게 나오는 거임?", ""),
        ("부정선거 의혹 기준이 뭐임", ""),
        ("국힘 지지자들 온라인 세력 과시가 그렇게 심한가", ""),
        ("온라인 지지 과시도 이제는 좀", ""),
        (
            "서울 출구조사 이거 보고도 부정 아니란 말이 나오냐",
            "서울 출구조사 결과랑 실제 득표율 차이 좀 너무한 거 아니냐\n이거 보고도 그냥 넘어가란 건가",
        ),
        ("야 이거 봐라 출구조사 차이 개크네", ""),
        ("서울 표본 이거 누가 봐도 확정임", ""),
    ]

    for title, content in failures:
        assert naturalness.structure_failure_reasons(title, content), title


def test_narrow_board_reactions_survive_structure_check():
    examples = [
        ("서울 출구조사 차이는 좀 크게 보이는데", "초반 숫자만 보고 박는 건 빠른 듯"),
        ("그 부정 기준을 출구조사 차이로만 잡는 거임?", "그럼 예전 선거도 다 걸리는 거 아닌가"),
        ("개표방송 AI 떡칠은 좀 깨네", "숫자보다 화면이 더 정신없음"),
        ("서울 표본이 원래 저렇게 튀었나", "그 차이 하나로 결론 박기엔 좀 빠른 듯"),
        ("50퍼 표는 좀 오래 보이긴 하네", "저 숫자만 보고 결론 박기엔 애매함"),
    ]

    for title, content in examples:
        assert not naturalness.structure_failure_reasons(title, content), title


def test_outsider_moderation_reactions_are_rejected():
    examples = [
        (
            "갤 분위기 좀 심각한데",
            "매번 똑같은 표현으로 싸우는 거 지겹지 않나",
        ),
        (
            "차단 기준 왜 자꾸 바뀌냐?",
            "어떤 건 되고 어떤 건 안되고 알 수가 없음",
        ),
        (
            "인류 역사상 최악의 범죄라는 게 특정 인종에게만 해당되는 건 아닐 텐데",
            "이런 식으로 몰아가는 게 맞는 건지 잘 모르겠음",
        ),
        (
            "인류 역사 기여 그거 기준이 너무 좁지 않나?",
            "어떤 부분만 보고 말하는 건지 모르겠음",
        ),
    ]

    for title, content in examples:
        assert naturalness.has_outsider_moderation_phrasing(title, content), title
        assert "외부인식 게시판 비평" in naturalness.structure_failure_reasons(
            title,
            content,
        )


def test_concrete_participant_reactions_are_not_outsider_moderation():
    examples = [
        ("공짜김밥이면 두 줄은 챙겨야지 ㅋㅋ", "한 줄 먹고 끝내긴 아까움"),
        ("기자회견 30분 만에 잡은 건 빠르네", "자료는 미리 들고 있던 듯"),
        ("외행성 사진 노이즈 생각보다 적네", "전 사진보다 고리 쪽은 잘 보임"),
    ]

    for title, content in examples:
        assert not naturalness.has_outsider_moderation_phrasing(title, content), title
        assert not naturalness.structure_failure_reasons(title, content), title


def test_person_callouts_and_complaint_judgments_are_rejected():
    examples = [
        (
            "재승아 왜 그렇게 씀",
            "굳이 저렇게까지 말하는 이유가 궁금하네",
            "특정 유저 호명/저격",
        ),
        (
            "전통 위계 문화는 뿌리 깊은 문제임",
            "가족 내 갈등이나 억압 구조가 세대까지 이어진다는 거 보면 ㄹㅇ",
            "불평/지적형 결론",
        ),
        (
            "시위 참여해도 바뀌는 거 크게 없음",
            "솔직히 시간만 쓰는 느낌이라 피곤함",
            "불평/지적형 결론",
        ),
    ]

    for title, content, reason in examples:
        reasons = naturalness.structure_failure_reasons(title, content)
        assert reason in reasons, title


def test_explanatory_ai_phrasing_is_rejected():
    assert naturalness.has_explanatory_ai_phrasing(
        "스타벅스 불매가 표심에 영향 줬다고 보는 거 ㄹㅇ?",
        "이게 그렇게까지 파급력이 있었던 건가 싶음. 일부 여론은 그랬을 수도 있지만 전체 판도를 바꿀 정도는 아닌데",
    )
    assert naturalness.structure_failure_reasons(
        "스타벅스 불매가 표심에 영향 줬다고 보는 거 ㄹㅇ?",
        "이게 그렇게까지 파급력이 있었던 건가 싶음. 일부 여론은 그랬을 수도 있지만 전체 판도를 바꿀 정도는 아닌데",
    )
    assert not naturalness.has_explanatory_ai_phrasing(
        "그 불매로 갈렸다는 건 좀 빠른 듯",
        "표 얘기까지 붙이기엔 아직 애매함",
    )


def test_gallery_style_can_allow_long_laugh_without_allowing_calls():
    style_profile = {"allow_long_laugh": True}

    assert not naturalness.structure_failure_reasons(
        "평택 개표 이건 웃기네 ㅋㅋㅋㅋㅋㅋㅋㅋ",
        "",
        style_profile=style_profile,
    )
    assert naturalness.structure_failure_reasons(
        "야 이거 봐라 평택 개표 ㅋㅋㅋㅋㅋㅋㅋㅋ",
        "",
        style_profile=style_profile,
    )


def test_question_skeleton_signatures_are_policy_driven():
    assert naturalness.question_skeleton_signature("투표 얘기 왜 자꾸 나옴", "") == "frequency_complaint"
    assert naturalness.question_skeleton_signature("야대기 무슨 뜻임", "") == "definition_probe"
    assert naturalness.question_skeleton_signature("투표 거부 하면 뭐가 달라지냐", "") == "effect_question"
    assert naturalness.question_skeleton_signature("투표 거부가 그렇게 쉽나", "") == "ease_question"
    assert naturalness.question_skeleton_signature("투표 거부 얘기 벌써 나오는 게 맞나", "") == "timing_question"
    assert naturalness.question_skeleton_signature("목성 중력으로 행성 공장 가능?", "") == "possibility_question"
    assert naturalness.question_skeleton_signature("일라이 재혼 이거 진짜냐?", "") == "truth_or_trend_probe"
    assert naturalness.question_skeleton_signature("부산 돼지국밥 진짜 맛있나?", "") == "truth_or_trend_probe"
    assert naturalness.question_skeleton_signature("환율 1400이면 체감 바로 오겠는데", "") == ""


def test_question_skeleton_labels_are_readable():
    assert naturalness.question_skeleton_label("frequency_complaint") == "빈도 불평형"
    assert naturalness.question_skeleton_label("missing") == "missing"


def test_reaction_skeletons_catch_reused_non_question_frames():
    assert naturalness.reaction_skeleton_signature(
        "투표지 오류 책임은 누가 지는 건데",
        "",
    ) == "responsibility_probe"
    assert naturalness.reaction_skeleton_signature(
        "투표지 오류는 그냥 그러려니 함",
        "",
    ) == "resigned_dismissal"
    assert naturalness.reaction_skeleton_signature(
        "이번 우주 사진 해상도 미쳤네",
        "전에 보던 거랑 차원이 다름",
    ) == "unsupported_history"
    assert naturalness.reaction_skeleton_signature(
        "투표 거부 드립 요즘 많이 보이네",
        "뭔가 계속 도는 거 같음",
    ) == "trend_watcher"
    assert naturalness.reaction_skeleton_signature(
        "태양계 외행성 관측값 새로 떴네",
        "스펙트럼 차이가 꽤 큼",
    ) == ""


def test_persona_angle_preferences_accept_lists():
    preferences = naturalness.persona_angle_preferences()

    assert preferences["analytical"][:2] == (
        "detail_extension",
        "scene_extension",
    )
    assert naturalness.persona_angle_overrides()["analytical"] == (
        "detail_extension"
    )
    assert preferences["light_joker"][0] == "light_humor"


def test_question_punctuation_is_added_without_moving_laughter():
    assert naturalness.ensure_question_punctuation("다른 선거 때도 늘 나오지 않았나") == (
        "다른 선거 때도 늘 나오지 않았나?"
    )
    assert naturalness.ensure_question_punctuation("이게 맞냐ㅋㅋ") == "이게 맞냐?ㅋㅋ"
    assert naturalness.ensure_question_punctuation("예수님덜 이거 왜 이럼") == (
        "예수님덜 이거 왜 이럼?"
    )
    assert naturalness.ensure_question_punctuation("글 일곱개 써야하는 게 진짜임") == (
        "글 일곱개 써야하는 게 진짜임?"
    )
    assert naturalness.ensure_question_punctuation("예수님덜 여기서 뭐하는 거임") == (
        "예수님덜 여기서 뭐하는 거임?"
    )
    assert naturalness.ensure_question_punctuation("보드게임 카페는 수익이 얼마나 남음") == (
        "보드게임 카페는 수익이 얼마나 남음?"
    )
    assert naturalness.ensure_question_punctuation("마피아 게임 몇 명 필요함") == (
        "마피아 게임 몇 명 필요함?"
    )
    assert naturalness.ensure_question_punctuation("그건 맞음") == "그건 맞음"
    assert naturalness.ensure_question_punctuation("이 계산이 맞음") == "이 계산이 맞음"


def test_question_punctuation_is_added_to_body_and_comment_lines():
    assert naturalness.ensure_question_punctuation_in_lines(
        "성욕이 뭔 상관이냐\n그냥 피곤해서 그런 거 아님"
    ) == "성욕이 뭔 상관이냐?\n그냥 피곤해서 그런 거 아님?"
    assert naturalness.ensure_question_punctuation_in_lines(
        "무리수 아님ㅋㅋ"
    ) == "무리수 아님?ㅋㅋ"
    assert naturalness.ensure_question_punctuation_in_lines(
        "양도 많고 냄새도 안 나서 좋았음"
    ) == "양도 많고 냄새도 안 나서 좋았음"


def test_direct_question_detection_handles_omitted_punctuation():
    assert naturalness.is_direct_question("투표지 기준 매번 바뀌나")
    assert naturalness.is_direct_question("그 기준이 맞냐ㅋㅋ")
    assert naturalness.is_direct_question("예수님덜 이거 왜 이럼")
    assert naturalness.is_direct_question("글 일곱개 써야하는 게 진짜임")
    assert not naturalness.is_direct_question("저 기준은 매번 달라짐")
    assert not naturalness.is_direct_question("오늘 간식은 바나나")


def test_incomplete_title_endings_are_rejected():
    failures = [
        "황인종은 극악무도한 만행만 한다 이건 좀",
        "방사능 새우 먹으면 외계인 된다는 말",
        "징역형으로 부족하다는 거 좀",
        "징역형만으론 부족하다는 건 좀",
        "시위 나가는 거 솔직히 좀",
        "골드번호 응모 매번 해도",
        "외행성 사진 화질 좋아지면",
        "목성 중력으로 행성 제조 가능하단 거",
        "창고 정리하다 나온 카드들 이거",
    ]

    for title in failures:
        assert naturalness.has_incomplete_title(title), title
        assert "판단이 끝나지 않은 제목" in naturalness.structure_failure_reasons(
            title,
            "",
        )

    assert not naturalness.has_incomplete_title("방사능 새우는 그냥 농담 같음")


def test_unsupported_personal_claims_are_rejected():
    assert naturalness.has_unsupported_personal_claim(
        "1만 꽝이면 나름 선방 아님?",
        "이 정도면 양반이지 난 10만 날려봄",
    )
    assert naturalness.has_unsupported_personal_claim(
        "골드번호 응모 매번 해도",
        "당첨된 적이 없다 ㄹㅇ",
    )
    assert "근거 없는 개인 경험" in naturalness.structure_failure_reasons(
        "1만 꽝이면 나름 선방 아님?",
        "이 정도면 양반이지 난 10만 날려봄",
    )
    assert not naturalness.has_unsupported_personal_claim(
        "1만 꽝이면 나름 선방임",
        "확률표만 보면 그 정도면 낮은 편은 아닌 듯",
    )


def test_gallery_name_commentary_is_meta_reaction():
    assert naturalness.has_hard_meta_reaction("갤 이름이 우주인데 ㅋㅋ", "")


def test_repetitive_review_batch_exceeds_question_budget():
    titles = [
        "투표지 오류 기준 매번 바뀜?",
        "1000개 오류가 진짜 그냥 오류임?",
        "1000개 투표지 가지고 재선거는 너무 나간 거 아님?",
        "노동의 가치 또 나옴",
        "1000개 오류 ㅋㅋㅋㅋㅋ",
        "선관위 투표지 오류 그거 어차피",
        "코스피 이거 언제쯤 다시 오름",
        "1000개 오류 다른 선거는 어땠음",
        "투표지 오류 다시 보자는 거면",
        "1000개 오류 << 이거 다른 의미일 수도 있지 않나",
    ]

    question_count = sum(naturalness.is_direct_question(title) for title in titles)

    assert naturalness.direct_question_cap(len(titles)) == 1
    assert question_count > naturalness.direct_question_cap(len(titles))
