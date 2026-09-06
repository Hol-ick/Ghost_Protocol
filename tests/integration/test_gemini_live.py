"""Opt-in, billable, synthetic JSON check; never contacts a board."""
import json
import os
import pytest
from dotenv import load_dotenv
from ghost_protocol.application.gemini_client import GeminiClient
from ghost_protocol.application.llm_provider import LLMRequest

pytestmark = pytest.mark.skipif(os.getenv('RUN_GEMINI_LIVE') != '1', reason='explicit opt-in required for paid API smoke')


def test_gemini_json_roundtrip():
    load_dotenv('.env')
    client = GeminiClient(api_key=os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY', ''),
                          model=os.getenv('GEMINI_MODEL_NAME', 'gemini-2.5-flash'))
    result = client.generate(LLMRequest(task='integration_smoke', system='Return JSON only.',
        prompt='Return {"ok":true}.', json_schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']},
        temperature=0, max_output_tokens=64))
    assert json.loads(result.text)['ok'] is True
    assert result.usage['total_token_count'] > 0
