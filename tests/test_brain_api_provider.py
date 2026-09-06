import json

from ghost_protocol.brain import GhostBrain
from ghost_protocol.application.gemini_client import GeminiClient
from ghost_protocol.application.llm_provider import LLMResponse


def test_default_is_gemini_even_when_old_ollama_values_remain(monkeypatch):
    monkeypatch.delenv('LLM_PROVIDER', raising=False)
    monkeypatch.delenv('GEMINI_MODEL_NAME', raising=False)
    monkeypatch.setenv('OLLAMA_MODEL', 'qwen2.5:7b')
    brain = GhostBrain()
    assert isinstance(brain.provider, GeminiClient)
    assert brain.model_name == 'gemini-2.5-flash'
    assert brain.is_api
    assert brain.fallback_model_names == ()


def test_api_passes_full_master_and_persona_despite_local_tuning(monkeypatch):
    from ghost_protocol import brain as module
    from ghost_protocol import prompt_manager as pm

    class Capture:
        def generate(self, request):
            self.request = request
            return LLMResponse(text=json.dumps({'title': '토성 고리', 'content': '고리 아래 그림자가 보임', 'target_comments': []}),
                               model='gemini-2.5-flash', usage={}, raw={'done_reason': 'stop'})

    provider = Capture()
    brain = GhostBrain(provider=provider, model_name='gemini-2.5-flash')
    monkeypatch.setenv('LLM_DRAFT_PIPELINE_MODE', 'structured')
    monkeypatch.setenv('LLM_PROMPT_MODE', 'focused')
    monkeypatch.setenv('LLM_JSON_SCHEMA_MODE', '0')
    monkeypatch.setattr(module, 'compile_post_prompt', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not compact API prompt')))
    monkeypatch.setattr(brain, '_get_style_examples', lambda *a, **k: [])
    original_render = pm.render
    captured = {}

    def render(name, **kwargs):
        rendered = original_render(name, **kwargs)
        if name == 'generate_post.txt':
            captured.update(prompt=rendered, tone=kwargs['tone_instruction'])
        return rendered

    monkeypatch.setattr(pm, 'render', render)
    brain.generate_post('토성 고리와 그림자 사진', 'universe', tone='neutral', context_hours=0)
    assert captured['prompt'] in provider.request.prompt
    assert captured['tone'] in provider.request.prompt
    assert provider.request.json_schema['properties']['target_comments']['items']['required'] == ['post_no', 'comment']
