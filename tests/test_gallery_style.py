from ghost_protocol.domain import gallery_style


def test_build_style_profile_detects_baseball_like_surface_habits():
    profile = gallery_style.build_style_profile(
        {
            "gallery_id": "baseball_new13",
            "titles": [
                "평택이 진짜 개레전드네 ㅋㅋㅋㅋㅋㅋㅋㅋ",
                "정원오 후보 이건 좀 아니지 않냐",
                "오세훈 역전각 ㄷㄷ",
                "출구조사 <- 이거 너무 빨리 박은듯",
            ],
            "comments": [
                "이건 좀 웃기네 ㅋㅋㅋㅋ",
                "ㄹㅇ 저 숫자는 봐야함",
            ],
        }
    )

    assert profile["gallery_name"] == "국내야구 갤러리"
    assert profile["laugh_ratio"] > 0
    assert profile["shortener_ratio"] > 0
    assert profile["allow_long_laugh"]
    assert any("웃음 꼬리" in rule for rule in profile["rules"])


def test_prompt_block_is_empty_without_rules():
    assert gallery_style.prompt_block({"rules": []}) == ""


def test_prompt_block_renders_generation_only_style_rules():
    profile = gallery_style.build_style_profile(
        {
            "gallery_id": "baseball_new13",
            "titles": ["평택 개표 ㅋㅋㅋㅋㅋㅋㅋㅋ", "서울 표본 ㄷㄷ"],
            "comments": ["ㄹㅇ ㅋㅋㅋㅋㅋㅋ"],
        }
    )

    block = gallery_style.prompt_block(profile)

    assert "갤러리별 문체 프로필" in block
    assert "금지 표현" in block
