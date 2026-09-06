"""Safe, operator-facing diagnostics for a guarded board collection run."""

from __future__ import annotations

from urllib.parse import urlsplit


_REASON_MEANINGS = {
    'http_0': (
        'HTTP 상태를 받기 전에 요청이 끝났습니다. 브라우저 또는 전송 연결 문제, '
        '응답 이전 차단 등 여러 경우가 가능하므로 이 코드만으로 차단을 확정하지 않습니다.'
    ),
    'transport_error': (
        '브라우저 또는 전송 계층에서 오류가 발생했습니다. HTTP 응답을 정상 수신하지 못한 상태입니다.'
    ),
    'empty_body': (
        '응답은 도착했지만 본문이 비어 있습니다. 수집기는 빈 화면을 정상 자료로 해석하지 않고 중단했습니다.'
    ),
    'blocked_marker': (
        '응답 본문에서 차단 표식을 감지했습니다. 추가 요청 없이 수집을 중단했습니다.'
    ),
    'request_budget_exhausted': (
        '이번 수집의 요청 예산에 도달했습니다. 추가 요청 없이 수집을 중단했습니다.'
    ),
}


def _text(value: object, *, fallback: str = '') -> str:
    value = str(value or '').strip()
    return value or fallback


def _safe_path(value: object) -> str:
    """Show only the path portion even when a non-guard fixture has a query."""
    return urlsplit(_text(value, fallback='/')).path or '/'


def _reason_meaning(reason: str) -> str:
    if reason in _REASON_MEANINGS:
        return _REASON_MEANINGS[reason]
    if reason.startswith('http_'):
        return 'HTTP 응답 상태가 정상 범위를 벗어났습니다. 아래 요청 원장에서 상태와 수집 단계를 확인하세요.'
    return '수집 보호 장치가 중단을 기록했습니다. 아래 요청 원장과 진행 로그를 먼저 확인하세요.'


def collection_access_diagnostic(report: dict | None) -> dict[str, object]:
    """Translate the already-sanitized access report into stable UI fields."""
    source = report if isinstance(report, dict) else {}
    reason = _text(source.get('reason'), fallback='unknown')
    rows: list[dict[str, str]] = []
    for event in source.get('events') or []:
        if not isinstance(event, dict):
            continue
        status = event.get('status')
        rows.append(
            {
                '시각': _text(event.get('at'), fallback='기록 없음'),
                '요청': f"{_text(event.get('method'), fallback='?')} · {_text(event.get('kind'), fallback='unknown')}",
                '시도': '예' if event.get('attempted', True) else '아니오',
                'HTTP': str(status if status is not None else '—'),
                '본문': f"{max(0, int(event.get('bytes') or 0))} B",
                '경로': _safe_path(event.get('path')),
                '판정': _text(event.get('reason'), fallback='정상'),
            }
        )
    request_count = max(0, int(source.get('request_count') or 0))
    request_budget = max(0, int(source.get('request_budget') or 0))
    return {
        'reason': reason,
        'status': _text(source.get('status'), fallback='unknown'),
        'purpose': _text(source.get('purpose'), fallback='studio_read'),
        'meaning': _reason_meaning(reason),
        'request_label': f'{request_count} / {request_budget} 요청' if request_budget else f'{request_count} 요청',
        'events': rows,
    }


def collection_job_log_lines(job: dict | None) -> list[str]:
    """Keep legacy progress callbacks readable without exposing unrelated fields."""
    if not isinstance(job, dict):
        return []
    lines: list[str] = []
    for entry in job.get('logs') or []:
        if not isinstance(entry, dict):
            continue
        at = _text(entry.get('at'), fallback='시간 없음')
        message = _text(entry.get('message'), fallback='기록 없음')
        lines.append(f'{at}  {message}')
    return lines
