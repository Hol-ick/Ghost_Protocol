from ghost_protocol.domain import comment_alignment


def test_target_comment_requires_target_post_overlap_not_comment_only_overlap():
    assert not comment_alignment.target_comment_fits_draft(
        "아발론도 인원수는 좀 타는데 시크릿히틀러보다는 유연함",
        title="시크릿히틀러는 최소 인원수가 좀",
        content="5인도 안 되면 아예 시작을 못하는 경우가 많다",
        target_title="당신은 탐정입니다 터널 집에 21번 카드 없는 사람 있음?",
        target_content="보드게임카페인데 21번 카드 없는데 빌려줄 사람 없음?",
    )
    assert not comment_alignment.target_comment_fits_draft(
        "테이블 돌리는 것도 중요함 게임 시간 긴 거 하면 다음 손님 못 받음",
        title="보드게임 카페 운영은 생각보다 손 많이 감",
        content="게임 관리도 일이고 테이블 회전도 신경 써야 함",
        target_title="부부끼리 할만한 게임 추천좀",
        target_content="둘이서 할만한 게임 그 몸으로 합체하는 거 말고",
    )


def test_target_comment_allows_specific_boardgame_overlap():
    assert comment_alignment.target_comment_fits_draft(
        "아발론도 인원수는 좀 타는데 시크릿히틀러보다는 유연함",
        title="시크릿히틀러는 최소 인원수가 좀",
        content="5인도 안 되면 아예 시작을 못하는 경우가 많다",
        target_title="마피아게임중에 존잼겜 추천점요",
        target_content="스파이폴 아발론 시크릿히틀러 해봤는데 인원수 때문에 고민됨",
    )
