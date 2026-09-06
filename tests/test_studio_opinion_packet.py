import pytest

from ghost_protocol.studio.opinion_packet import build_opinion_packet, is_board_collection


def collected_source():
    return {
        'source_kind': 'board_collection',
        'gallery_id': 'universe',
        'titles': ['목성 구름 띠가 유난히 진함', '망원경 설치 뒤 구름 들어옴'],
        'comments': ['구름 타이밍 진짜 좋네', '오늘 목성 잘 보이긴 함'],
        'raw_posts': [
            {
                'title': '목성 구름 띠가 유난히 진함',
                'content': '저녁에 보니까 남쪽 띠가 진하게 보였음',
                'comments': ['구름 타이밍 진짜 좋네', '오늘 목성 잘 보이긴 함'],
            },
        ],
        'source_access': {'status': 'ok'},
    }


def analysis():
    return {
        'hot_topics': ['목성 구름 띠'],
        'topic_slots': ['목성 구름 띠 관측'],
        'sentiment': '가벼운 관찰',
        'memes': ['구름 타이밍'],
        'summary': '관측 장면과 구름 타이밍 반응이 섞여 있다.',
        'ai_analysis': '목성 관측을 두고 세부 명암과 날씨 타이밍을 짧게 주고받는다.',
        'generation_guidance': '관측된 장면 하나로 바로 반응한다.',
    }


def test_packet_compiles_collected_posts_comments_and_analysis():
    packet = build_opinion_packet(collected_source(), analysis(), 0)

    assert '[게시판 여론 패킷]' in packet
    assert '게시판 ID: universe' in packet
    assert '선택 소재: 목성 구름 띠 관측' in packet
    assert '원본 글: 목성 구름 띠가 유난히 진함' in packet
    assert '원본 본문: 저녁에 보니까 남쪽 띠가 진하게 보였음' in packet
    assert '원본 댓글: 구름 타이밍 진짜 좋네' in packet
    assert '직접 입력' not in packet
    assert '작성자' not in packet


def test_packet_falls_back_to_cleaned_title_and_comment_lists():
    source = collected_source()
    source['raw_posts'] = []
    packet = build_opinion_packet(source, analysis(), 4)

    assert '선택 소재: 목성 구름 띠 관측' in packet
    assert '원본 글: 목성 구름 띠가 유난히 진함' in packet
    assert '원본 댓글: 구름 타이밍 진짜 좋네' in packet


def test_packet_rejects_non_collection_or_parse_failed_analysis():
    source = collected_source()
    source['source_kind'] = 'manual'
    assert not is_board_collection(source)
    with pytest.raises(ValueError, match='수집'):
        build_opinion_packet(source, analysis(), 0)

    failed = analysis() | {'_parse_error': True}
    with pytest.raises(ValueError, match='파싱'):
        build_opinion_packet(collected_source(), failed, 0)
