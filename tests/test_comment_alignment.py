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


def test_domain_anchored_comment_needs_same_domain_not_generic_overlap():
    assert not comment_alignment.comment_fits_draft(
        "교황 같은 중심이 없으면 종교 쪽은 흔들릴 수밖에 없음",
        title="빅뱅 이후 물질 중심 흐름 다시 봐야 하는 거 아님?",
        content="중심이라는 단어만 같고 실제로는 우주 팽창 얘기임",
        target_title="빅뱅 직후 우주 팽창",
        target_content="중심 좌표를 어떻게 잡는지 얘기",
    )

    assert comment_alignment.comment_fits_draft(
        "목성 중력 때문에 먼지가 모인다는 게 신기하네",
        title="목성 중력으로 행성 공장 만드는 거",
        content="먼지가 모이는 장면이 핵심인 듯",
        target_title="목성 중력 행성 공장",
        target_content="먼지와 중력 이야기",
    )


def test_same_source_detail_comment_can_survive_without_exact_word_overlap():
    assert comment_alignment.comment_fits_draft(
        "대관비가 은근 커서 회전율 봐야 됨",
        title="보드게임 카페는 수익이 얼마나 남음?",
        content="테이블 오래 잡히면 계산이 빡셀 것 같긴 함",
        target_title="보드게임 카페 수익 구조",
        target_content="카페 운영비랑 회전율 이야기",
    )
