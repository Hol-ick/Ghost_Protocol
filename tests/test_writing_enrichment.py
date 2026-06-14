from ghost_protocol.domain import writing_enrichment


def test_title_driven_profile_prefers_short_caption_body():
    raw = {
        "raw_posts": [
            {"title": "로또 1만개 언제 다함", "content": "", "comments": []},
            {"title": "아침 간식 저거 괜찮네", "content": "사진만 봐도 배고픔", "comments": []},
            {"title": "외행성 사진 이제 잘 보이면 좋겠다", "content": "", "comments": []},
        ]
    }

    profile = writing_enrichment.build_composition_profile(raw)

    assert profile["shape"] == "title_driven"
    assert profile["depth"] == "shallow"
    assert any("title-driven" in rule for rule in profile["rules"])
    assert "[Composition Profile]" in writing_enrichment.prompt_block(profile)


def test_body_supporting_profile_allows_two_short_lines():
    raw = {
        "raw_posts": [
            {
                "title": "외행성 사진 해상도 좋아지는 거",
                "content": "망원경 보정까지 들어가면 생각보다 많은 정보가 남는 듯. 대기 흔들림만 줄어도 차이가 크고, 같은 사진이라도 노출을 여러 장 쌓으면 행성 주변 먼지대까지 어느 정도 구분된다던데 실제 결과가 궁금함.",
                "comments": ["그 정도면 관측값도 꽤 쓸만하지 않나"],
            },
            {
                "title": "목성 주변 먼지대 이야기",
                "content": "행성 형성 시뮬레이션 보면 작은 먼지가 계속 충돌하면서 커지는 과정이 핵심이라던데 실제 관측이 궁금함. 목성 중력권에서 작은 입자가 어떤 식으로 정렬되는지까지 보면 행성 공장 같은 표현이 왜 나왔는지도 조금 이해될 듯.",
                "comments": ["직접 보긴 어렵겠지"],
            },
        ]
    }

    profile = writing_enrichment.build_composition_profile(raw)

    assert profile["shape"] == "body_supporting"
    assert profile["depth"] in {"compact", "expanded"}
    assert any("two short body lines" in rule for rule in profile["rules"])


def test_sparse_comment_profile_allows_empty_comments():
    raw = {
        "raw_posts": [
            {"title": "제목 하나", "content": "본문", "comments": []},
            {"title": "제목 둘", "content": "", "comments": []},
        ]
    }

    profile = writing_enrichment.build_composition_profile(raw)
    block = writing_enrichment.comment_prompt_block(profile)

    assert profile["comment_presence_ratio"] == 0
    assert "empty array" in block


def test_dense_comment_profile_attaches_to_detail():
    raw = {
        "raw_posts": [
            {"title": "글 하나", "content": "본문", "comments": ["댓글 하나"]},
            {"title": "글 둘", "content": "본문", "comments": ["댓글 둘", "댓글 셋"]},
            {"title": "글 셋", "content": "본문", "comments": ["댓글 넷"]},
        ]
    }

    profile = writing_enrichment.build_composition_profile(raw)
    block = writing_enrichment.comment_prompt_block(profile)

    assert profile["comment_presence_ratio"] == 1
    assert "concrete detail" in block
