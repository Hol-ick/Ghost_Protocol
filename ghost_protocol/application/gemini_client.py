"""Gemini generateContent adapter; one accounted HTTP call per generation."""

from __future__ import annotations

import re
import requests

from .llm_provider import LLMRequest, LLMResponse, LLMResponseError, LLMUnavailableError, LLMTimeoutError


class GeminiClient:
    def __init__(self, *, api_key: str, model: str = 'gemini-2.5-flash',
                 timeout_seconds: float = 90, session=None):
        self._api_key = str(api_key or '').strip()
        if not re.fullmatch(r'gemini-[a-zA-Z0-9._-]+', model):
            raise ValueError('GEMINI_MODEL_NAME must be a Gemini model ID')
        self.model = model
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._session = session or requests.Session()

    def health(self) -> dict:
        # No billable requests or repeated network probes on Streamlit reruns.
        configured = bool(self._api_key)
        return {'ok': configured, 'model_available': configured, 'model': self.model,
                'provider': 'gemini', 'verified': False, 'status': 'configured' if configured else 'missing_key',
                'error': '' if configured else 'GEMINI_API_KEY가 없습니다. 로컬 .env에 설정하세요.'}

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self._api_key:
            raise LLMUnavailableError('GEMINI_API_KEY가 없습니다. 로컬 .env에 설정하세요.')
        config = {'temperature': request.temperature, 'maxOutputTokens': request.max_output_tokens,
                  'responseMimeType': 'application/json'}
        if request.json_schema is not None:
            config['responseJsonSchema'] = request.json_schema
        # Short structured tasks should spend their budget on the actual answer.
        if self.model.startswith('gemini-2.5-flash'):
            config['thinkingConfig'] = {'thinkingBudget': 0}
        payload = {'contents': [{'role': 'user', 'parts': [{'text': request.prompt}]}],
                   'generationConfig': config}
        if request.system:
            payload['systemInstruction'] = {'parts': [{'text': request.system}]}
        try:
            response = self._session.post(
                f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent',
                headers={'x-goog-api-key': self._api_key, 'Content-Type': 'application/json'},
                json=payload, timeout=(10, self.timeout_seconds), allow_redirects=False,
            )
        except requests.Timeout:
            raise LLMTimeoutError('Gemini API 응답 시간이 초과됐습니다.') from None
        except requests.RequestException:
            raise LLMUnavailableError('Gemini API 네트워크 연결에 실패했습니다.') from None
        if response.status_code != 200:
            hints = {400: '요청 또는 API 키 설정 확인', 401: 'API 키 인증 실패',
                     403: 'API 사용 권한 확인', 404: '모델 지원 여부 확인',
                     429: 'rate limit / quota exceeded — 할당량·결제 확인'}
            # Do not log upstream error bodies: they can echo credentials/prompts.
            raise LLMUnavailableError(
                f'Gemini API HTTP {response.status_code}: {hints.get(response.status_code, "서비스 오류")}'
            )
        try:
            data = response.json()
            candidates = data.get('candidates') or []
            candidate = candidates[0] if candidates else {}
            reason = str(candidate.get('finishReason') or '')
            if reason != 'STOP':
                raise LLMResponseError(f'Gemini 응답 미완료 또는 차단: {reason or "NO_CANDIDATE"}')
            parts = candidate.get('content', {}).get('parts', [])
            text = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
            if not text:
                raise LLMResponseError('Gemini API가 빈 응답을 반환했습니다.')
            meta = data.get('usageMetadata') or {}
            usage = {dst: int(meta.get(src) or 0) for src, dst in (
                ('promptTokenCount', 'prompt_token_count'), ('candidatesTokenCount', 'candidates_token_count'),
                ('totalTokenCount', 'total_token_count'), ('thoughtsTokenCount', 'thoughts_token_count'),
                ('cachedContentTokenCount', 'cached_content_token_count'))}
        except (ValueError, TypeError, AttributeError, KeyError, IndexError):
            raise LLMResponseError('Gemini API 응답 형식을 해석할 수 없습니다.') from None
        return LLMResponse(text=text, model=str(data.get('modelVersion') or self.model), usage=usage,
                           raw={'done_reason': 'stop', 'finishReason': reason})
