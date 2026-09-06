import pytest
import requests

from ghost_protocol.application.gemini_client import GeminiClient
from ghost_protocol.application.llm_provider import LLMRequest, LLMResponseError, LLMUnavailableError, LLMTimeoutError


class Session:
    def __init__(self, payload=None, status=200, error=None):
        self.payload = payload
        self.status = status
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return type('Response', (), {'status_code': self.status, 'json': lambda _: self.payload})()


def result(text='{"title":"목성"}', reason='STOP'):
    return {'candidates': [{'content': {'parts': [{'text': text}]}, 'finishReason': reason}],
            'usageMetadata': {'promptTokenCount': 10, 'candidatesTokenCount': 5, 'totalTokenCount': 15}}


def test_full_request_and_usage():
    session = Session(result())
    client = GeminiClient(api_key='secret', session=session)
    request = LLMRequest(task='generate_post', system='페르소나 원문', prompt='전체 작문 지시', json_schema={'type': 'object'})
    response = client.generate(request)
    url, sent = session.calls[0]
    assert 'secret' not in url
    assert sent['headers']['x-goog-api-key'] == 'secret'
    assert sent['json']['contents'][0]['parts'][0]['text'] == request.prompt
    assert sent['json']['systemInstruction']['parts'][0]['text'] == request.system
    assert sent['json']['generationConfig']['responseJsonSchema'] == request.json_schema
    assert response.usage['prompt_token_count'] == 10
    assert response.raw['done_reason'] == 'stop'


@pytest.mark.parametrize('status', [401, 403, 404, 429, 503])
def test_http_failure_no_retry_or_secret_leak(status):
    session = Session({'error': {'message': 'secret'}}, status=status)
    client = GeminiClient(api_key='secret', session=session)
    with pytest.raises(LLMUnavailableError) as caught:
        client.generate(LLMRequest(task='test', system='', prompt='x'))
    assert 'secret' not in str(caught.value)
    assert str(status) in str(caught.value)
    assert len(session.calls) == 1


@pytest.mark.parametrize('payload', [result('', 'STOP'), result('{}', 'MAX_TOKENS'), {'promptFeedback': {'blockReason': 'SAFETY'}}, []])
def test_invalid_or_truncated_response_rejected(payload):
    with pytest.raises(LLMResponseError):
        GeminiClient(api_key='secret', session=Session(payload)).generate(LLMRequest(task='test', system='', prompt='x'))


def test_missing_key_health_is_local_and_generation_stops():
    session = Session(result())
    client = GeminiClient(api_key='', session=session)
    assert not client.health()['ok']
    with pytest.raises(LLMUnavailableError):
        client.generate(LLMRequest(task='test', system='', prompt='x'))
    assert not session.calls


def test_timeout_is_classified():
    with pytest.raises(LLMTimeoutError):
        GeminiClient(api_key='secret', session=Session(error=requests.Timeout())).generate(LLMRequest(task='test', system='', prompt='x'))
