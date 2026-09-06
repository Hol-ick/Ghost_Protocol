"""Real prompt builder through a mocked provider: no outbound requests."""
import json
import pytest

from ghost_protocol.studio.adapters import StudioBackend
from ghost_protocol.application.gemini_client import GeminiClient
from ghost_protocol.application.llm_provider import LLMResponse
from ghost_protocol import prompt_manager as pm


@pytest.mark.parametrize('model',['gemini-3.1-flash-lite','gemini-2.5-flash'])
def test_real_adapter_preserves_entire_master_prompt_and_persona(model, monkeypatch):
    monkeypatch.delenv('STUDIO_OFFLINE', raising=False)
    monkeypatch.setenv('GEMINI_API_KEY','not-a-real-key')
    rendered, captured, telemetry = [], [], []
    original_render = pm.render
    def observe_render(name, **kwargs):
        value = original_render(name, **kwargs)
        if name == 'generate_post.txt':
            rendered.append((value,kwargs))
        return value
    def fake_generate(self, request):
        captured.append(request)
        return LLMResponse(text=json.dumps({'title':'달의 경계','content':'명암 경계가 보임','target_comments':[]}),
            model=model,usage={'prompt_token_count':7000,'candidates_token_count':100},raw={'done_reason':'stop'})
    monkeypatch.setattr(pm,'render',observe_render)
    monkeypatch.setattr(GeminiClient,'generate',fake_generate)
    monkeypatch.setattr('requests.Session.post',lambda *a,**k:pytest.fail('Network is forbidden'))
    result = StudioBackend().generate({'gallery':'universe'},model,'analytical','달의 명암 경계','추가 검증 규칙',
        lambda *args:telemetry.append(args))
    assert result['title'] == '달의 경계'
    assert len(captured) == len(rendered) == len(telemetry) == 1
    assert rendered[0][0] in captured[0].prompt
    assert len(rendered[0][0]) > 5000
    assert '추가 검증 규칙' in captured[0].prompt
    assert pm.load_json('persona_profiles.json')['analytical']['vocab_style'] in captured[0].prompt
    assert telemetry[0][0] == model
    assert telemetry[0][1]['prompt'] == captured[0].prompt
    assert 'not-a-real-key' not in json.dumps(telemetry[0][1])
