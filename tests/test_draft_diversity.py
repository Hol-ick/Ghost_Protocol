from ghost_protocol.domain import draft_diversity


def test_safe_ending_signature_detects_bland_tails_only():
    assert draft_diversity.safe_ending_signature(
        "계룡산 근황 사진 보니까 좀 신기함",
        "안개 낀 장면이 묘하네",
    ) == "wonder"
    assert draft_diversity.safe_ending_signature(
        "아점 시간대면 그냥 기다리는 게 나음",
        "이 시간대는 애매하긴 함",
    ) == "ambiguous"
    assert draft_diversity.safe_ending_signature(
        "신기라는 단어 자체를 분석해봄",
        "본문 중간에만 나오는 단어면 결말 수렴은 아님",
    ) == ""


def test_safe_ending_cap_scales_with_batch_size():
    assert draft_diversity.safe_ending_cap(10) == 1
    assert draft_diversity.safe_ending_cap(20) == 2
