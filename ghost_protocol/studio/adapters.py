"""Real worker adapters; credentials and external IO never live in UI modules."""
from dataclasses import asdict
import os
import time
import sqlite3


class StudioBackend:
    def _allow_external(self):
        if os.getenv('STUDIO_OFFLINE') == '1':
            raise ValueError('오프라인 검증 모드: 외부 수집과 API 호출을 차단했습니다.')

    def collect(self, work, payload, log):
        self._allow_external()
        from ghost_protocol.scraper import TrendScraper
        with TrendScraper(purpose='studio_read') as scraper:
            return scraper.collect_trending(gallery_id=work['gallery'], gallery_type=work['gallery_type'],
                pages=payload['pages'], source_detail_limit=6, source_comments_per_post=3, progress_callback=log)

    def stored(self, work, payload, log):
        from ghost_protocol.config import DB_PATH
        # Read-only URI: no schema edits, no init_db side effects.
        from pathlib import Path
        if not Path(DB_PATH).exists():
            raise ValueError('기존 DB가 없습니다. 직접 자료를 입력하세요.')
        with sqlite3.connect(Path(DB_PATH).as_uri()+'?mode=ro', uri=True) as conn:
            conn.row_factory = sqlite3.Row
            posts = [dict(r) for r in conn.execute('SELECT post_id,title,content,created_at FROM posts WHERE gallery_id=? ORDER BY scraped_at DESC LIMIT 30', (work['gallery'],))]
        log(f'기존 DB에서 {len(posts)}개 읽음 — 새 수집 없음')
        return {'titles':[p['title'] for p in posts if p['title']], 'comments':[], 'raw_posts':posts,
                'gallery_id':work['gallery'],'origin':'기존 DB (과거 자료)', 'source_access':{'status':'ok'}}

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
        return self._brain(model, meter).analyze_trend(work['source'])

    def generate(self, work, model, tone, topic, rules, meter):
        if rules.strip():
            topic += '\n\n[운영자 추가 작문 규칙]\n' + rules
        return self._brain(model,meter).generate_post(topic, work['gallery'], tone=tone,
            context_hours=0, recent_posts=[], length='짧게 (1~2문장)', expected_slot='A')
