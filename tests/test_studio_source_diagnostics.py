from ghost_protocol.studio.source_diagnostics import (
    collection_access_diagnostic,
    collection_job_log_lines,
)


def test_http_zero_has_non_blocking_interpretation_and_safe_rows():
    diagnostic = collection_access_diagnostic(
        {
            'status': 'blocked',
            'reason': 'http_0',
            'request_count': 1,
            'request_budget': 20,
            'purpose': 'studio_read',
            'events': [
                {
                    'at': '2026-09-06T10:00:00',
                    'method': 'GET',
                    'kind': 'board_list',
                    'attempted': True,
                    'status': 0,
                    'bytes': 0,
                    'path': '/board/lists/?id=universe&no=private',
                    'reason': 'http_0',
                }
            ],
        }
    )

    assert '차단을 확정' in diagnostic['meaning']
    assert diagnostic['request_label'] == '1 / 20 요청'
    assert diagnostic['events'] == [
        {
            '시각': '2026-09-06T10:00:00',
            '요청': 'GET · board_list',
            '시도': '예',
            'HTTP': '0',
            '본문': '0 B',
            '경로': '/board/lists/',
            '판정': 'http_0',
        }
    ]


def test_known_stop_reasons_are_explained_and_job_logs_keep_time_order():
    empty = collection_access_diagnostic({'reason': 'empty_body', 'events': []})
    transport = collection_access_diagnostic({'reason': 'transport_error', 'events': []})

    assert '본문이 비어' in empty['meaning']
    assert '브라우저 또는 전송 계층' in transport['meaning']
    assert collection_job_log_lines(
        {
            'logs': [
                {'at': '10:00:00', 'message': '목록 수집 중'},
                {'at': '10:00:02', 'message': '수집 중단'},
            ]
        }
    ) == ['10:00:00  목록 수집 중', '10:00:02  수집 중단']
