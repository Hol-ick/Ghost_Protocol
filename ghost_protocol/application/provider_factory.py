"""Explicit backend selection. API is the default; never switch on failure."""

import os

from .gemini_client import GeminiClient
from .ollama_client import OllamaClient


def provider_name() -> str:
    name = os.getenv('LLM_PROVIDER', 'gemini').strip().lower() or 'gemini'
    if name not in {'gemini', 'ollama'}:
        raise ValueError('LLM_PROVIDER must be gemini or ollama')
    return name


def configured_model() -> str:
    if provider_name() == 'gemini':
        return os.getenv('GEMINI_MODEL_NAME', 'gemini-2.5-flash').strip() or 'gemini-2.5-flash'
    return os.getenv('OLLAMA_MODEL', 'qwen2.5:3b').strip() or 'qwen2.5:3b'


def create_provider(model_name=None):
    model = model_name or configured_model()
    if provider_name() == 'gemini':
        return GeminiClient(api_key=os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY', ''),
                            model=model, timeout_seconds=float(os.getenv('GEMINI_TIMEOUT_SEC', '90')))
    full = any(marker in model.lower() for marker in (':7b', ':8b', ':9b', ':14b', ':32b'))
    return OllamaClient(base_url=os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'), model=model,
                        timeout_seconds=float(os.getenv('OLLAMA_TIMEOUT_SEC', '120')),
                        num_ctx=int(os.getenv('OLLAMA_NUM_CTX', '8192' if full else '4096')),
                        keep_alive=os.getenv('OLLAMA_KEEP_ALIVE', '10m'))
