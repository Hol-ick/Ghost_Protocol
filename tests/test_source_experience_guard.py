from ghost_protocol.domain import naturalness


def test_source_discovery_should_not_be_rewritten_as_own_experience():
    assert naturalness.has_unsupported_personal_claim(
        "오랜만에 창고 정리하다 카드 발견함",
        "어릴 때 모으던 카드들인데 리미티드도 좀 있네",
    )
    assert "근거 없는 개인 경험" in naturalness.structure_failure_reasons(
        "오랜만에 창고 정리하다 카드 발견함",
        "어릴 때 모으던 카드들인데 리미티드도 좀 있네",
    )


def test_source_discovery_can_be_framed_as_visible_post():
    assert not naturalness.has_unsupported_personal_claim(
        "창고 정리글 보니까 리미티드 카드도 있네",
        "사진 기준이면 상태부터 봐야 할 듯",
    )
