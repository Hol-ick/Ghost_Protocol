"""Real worker adapters; credentials and external IO never live in UI modules."""
from dataclasses import asdict
import os
import time


class StudioBackend:
    def _allow_external(self):
        if os.getenv('STUDIO_OFFLINE') == '1':
            raise ValueError('오프라인 검증 모드: 외부 수집과 API 호출을 차단했습니다.')

    def collect(self, work, payload, log):
        self._allow_external()
        from .legacy_collection import collect_legacy_board
        source = collect_legacy_board(
            gallery_id=work['gallery'],
            gallery_type=work['gallery_type'],
            pages=payload['pages'],
            log=log,
        )
        source.update(source_kind='board_collection', origin='기존 Ghost Protocol 브라우저 수집')
        return source

    def _brain(self, model, meter):
        self._allow_external()
        from ghost_protocol.application.gemini_client import GeminiClient
        from ghost_protocol.brain import GhostBrain
        client = GeminiClient(api_key=os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY',''), model=model)
        class Measured:
            def generate(self, request):
                start = time.perf_counter()
                response, error = None, ''
                try:
                    response = client.generate(request)
                    return response
                except Exception as exc:
                    error = type(exc).__name__
                    raise
                finally:
                    meter(model, asdict(request), response, round(time.perf_counter()-start,3), error)
        brain = GhostBrain(provider=Measured(), model_name=model)
        brain._get_style_examples = lambda *a, **kw: []
        return brain

    def analyze(self, work, model, meter):
        return self._brain(model, meter).analyze_trend(work['source'], include_gallery_identity=False)

    def generate(self, work, model, tone, topic, rules, meter):
        if rules.strip():
            topic += '\n\n[운영자 추가 작문 규칙]\n' + rules
        return self._brain(model,meter).generate_post(topic, work['gallery'], tone=tone,
            context_hours=0, recent_posts=[], length='짧게 (1~2문장)', expected_slot='A')
