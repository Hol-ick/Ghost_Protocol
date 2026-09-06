"""Compile one bounded, collected-board opinion packet for the writer.

This module deliberately performs no model call.  It is the seam between the
read-only collector/analysis and the existing persona writer: only collection
output and its derived analysis may cross it.
"""
from __future__ import annotations

import re

from .policy import analysis_ready, source_ready


def _text(value, limit):
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:limit]


def _items(value, limit, item_limit):
    if not isinstance(value, list):
        return []
    return [_text(item, item_limit) for item in value if _text(item, item_limit)][:limit]


def is_board_collection(source):
    return bool(source_ready(source) and source.get('source_kind') == 'board_collection')


def _source_rows(source):
    rows = []
    for post in source.get('raw_posts', []) if isinstance(source.get('raw_posts'), list) else []:
        if not isinstance(post, dict) or post.get('is_bot') or post.get('is_noise'):
            continue
        title = _text(post.get('title') or post.get('source_title'), 160)
        content = _text(post.get('content'), 420)
        comments = _items(post.get('comments'), 3, 120)
        if title or content or comments:
            rows.append((title, content, comments))
        if len(rows) == 6:
            return rows
    if rows:
        return rows
    titles = _items(source.get('titles'), 20, 160)
    comments = _items(source.get('comments'), 18, 120)
    return [(title, '', []) for title in titles] + [('', '', [comment]) for comment in comments]


def build_opinion_packet(source, analysis, slot_index):
    """Return a writer input grounded in one collector result and one analysis.

    No author identity, access diagnostics, bot/noise samples, or arbitrary
    operator topic may enter this packet.  The writer gets only public text
    which has already passed the collector's bot/noise filters and its analysis.
    """
    if not is_board_collection(source):
        raise ValueError('정상 게시판 수집 결과가 필요합니다.')
    if not analysis_ready(analysis):
        raise ValueError('분석 파싱 실패 또는 분석 결과 없음')

    slots = _items(analysis.get('topic_slots'), 3, 100)
    topics = _items(analysis.get('hot_topics'), 4, 100)
    selected = (slots or topics or _items(source.get('titles'), 1, 160) or ['수집된 게시판 반응'])[int(slot_index) % max(1, len(slots or topics or _items(source.get('titles'), 1, 160) or ['x']))]
    lines = [
        '[게시판 여론 패킷]',
        f"게시판 ID: {_text(source.get('gallery_id'), 80)}",
        f'선택 소재: {selected}',
        f"정서: {_text(analysis.get('sentiment'), 80)}",
        '핵심 소재: ' + ', '.join(topics),
        '반복 표현: ' + ', '.join(_items(analysis.get('memes'), 4, 100)),
        '분위기 요약: ' + _text(analysis.get('summary'), 520),
        '여론 분석: ' + _text(analysis.get('ai_analysis'), 620),
        '작문 반영: ' + _text(analysis.get('generation_guidance'), 520),
        '',
        '[정제된 원문 글·댓글]',
    ]
    for title, content, comments in _source_rows(source):
        if title:
            lines.append('원본 글: ' + title)
        if content:
            lines.append('원본 본문: ' + content)
        for comment in comments:
            lines.append('원본 댓글: ' + comment)
    return '\n'.join(line for line in lines if line.strip())


__all__ = ['build_opinion_packet', 'is_board_collection']
