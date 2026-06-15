from ghost_protocol.domain import comment_alignment


def test_concrete_off_topic_comment_is_rejected():
    assert not comment_alignment.comment_fits_draft(
        "교황 같은 중심이 없으면 종교 쪽은 흔들릴 수밖에 없음",
        title="빅뱅 직후 우주 팽창 속도 다시 봐야 하는 거 아님?",
        content="관측값이랑 계산값 차이가 아직 남는 게 신기함",
        target_title="빅뱅 직후 우주 팽창 속도",
        target_content="허블 상수 차이 얘기",
    )


def test_concrete_matching_comment_is_kept():
    assert comment_alignment.comment_fits_draft(
        "망원경 성능 더 좋아지면 외행성 대기 성분도 보일 듯",
        title="외행성 대기 관측은 아직 망원경 성능이 관건인 듯",
        content="스펙트럼으로 보는 것도 한계가 있어 보임",
        target_title="외행성 대기 관측 근황",
        target_content="망원경 스펙트럼 이야기",
    )


def test_generic_reaction_needs_source_anchor():
    assert comment_alignment.comment_fits_draft(
        "ㄹㅇ 신기하네",
        title="계룡산 근황 사진 보니까 분위기 다르네",
        content="안개 낀 장면이 좀 묘함",
        target_title="계룡산 근황 사진",
        target_content="안개 낀 산 사진",
    )
    assert not comment_alignment.comment_fits_draft(
        "ㄹㅇ 신기하네",
        title="계룡산 근황 사진 보니까 분위기 다르네",
        content="안개 낀 장면이 좀 묘함",
        target_title="주말 점심 메뉴",
        target_content="아점 먹는 시간 이야기",
    )
