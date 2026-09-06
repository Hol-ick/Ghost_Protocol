"""Opt-in paid 10-pair benchmark. No board access or publication."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from ghost_protocol.brain import GhostBrain
from ghost_protocol import prompt_manager as pm
from ghost_protocol.application.gemini_client import GeminiClient

RATES = {'gemini-2.5-flash': ('0.30', '2.50', '0.03'),
         'gemini-3.1-flash-lite': ('0.25', '1.50', '0.025')}
CASES = [
    ('cynical', '망원경을 설치한 뒤 구름이 들어와 달이 가려졌다. 설치가 끝날 때까지는 달이 보였다.'),
    ('neutral', '토성 사진에서 고리의 그림자가 행성 표면을 가로지른다. 사진 한 장만 주어졌다.'),
    ('analytical', '같은 달 분화구를 찍은 사진 두 장 중 낮은 태양 각도의 사진에서 그림자가 더 길다.'),
    ('aggressive', '관측용 삼각대의 잠금 나사를 덜 조여 접안부를 만질 때마다 화면이 흔들렸다.'),
    ('aggro', '망원경 배율을 높인 사진은 더 크지만 낮은 배율 사진보다 윤곽이 흐리다. 동일 대상이다.'),
    ('monologue', '달의 밝은 면과 어두운 면 경계에 작은 분화구들이 줄지어 보이는 장면이다.'),
    ('ventilator', '관측 장소의 벤치는 이슬에 젖었고 장비 덮개에도 물방울이 맺혔다. 관측자는 서 있다.'),
    ('meta_observer', '합성 댓글 두 개가 같은 목성 사진을 보고 하나는 줄무늬, 다른 하나는 옆의 작은 점을 짚었다.'),
    ('doomer', '별을 찍는 도중 수평선 쪽 구름이 커지고 있다. 아직 관측 대상은 구름 밖에 있다.'),
    ('conviction_defender', '달을 처음 보는 사람이 작은 쌍안경으로도 분화구 주변의 명암 차이를 구분했다.'),
]


def cost_usd(model, usage):
    inp, out, cached = map(Decimal, RATES[model])
    p = int(usage.get('prompt_token_count', 0))
    c = int(usage.get('cached_content_token_count', 0))
    o = int(usage.get('candidates_token_count', 0)) + int(usage.get('thoughts_token_count', 0))
    assert 0 <= c <= p
    return (Decimal(p-c)*inp + Decimal(c)*cached + Decimal(o)*out) / Decimal(1_000_000)


class Capture:
    def __init__(self, client):
        self.client = client
        self.request = None
        self.response = None
        self.elapsed = 0

    def generate(self, request):
        assert self.request is None, 'Only one paid call per draft is allowed'
        self.request = asdict(request)
        start = time.perf_counter()
        try:
            self.response = self.client.generate(request)
            return self.response
        finally:
            self.elapsed = time.perf_counter() - start


def report(rows, folder, wall):
    summaries = {}
    for model in RATES:
        subset = [r for r in rows if r['model'] == model]
        summaries[model] = {
            'attempts': len(subset), 'ready': sum(r['ready'] for r in subset),
            'api_seconds': round(sum(r['api_seconds'] for r in subset), 3),
            'input_tokens': sum(r['usage'].get('prompt_token_count', 0) for r in subset),
            'output_tokens': sum(r['usage'].get('candidates_token_count', 0) for r in subset),
            'thinking_tokens': sum(r['usage'].get('thoughts_token_count', 0) for r in subset),
            'cached_tokens': sum(r['usage'].get('cached_content_token_count', 0) for r in subset),
            'usage_missing_calls': sum(not bool(r['usage']) for r in subset),
            'cost_usd': str(sum((Decimal(r['cost_usd']) for r in subset), Decimal(0))),
        }
    total = sum((Decimal(s['cost_usd']) for s in summaries.values()), Decimal(0))
    result = {'models': summaries, 'total_cost_usd': str(total), 'wall_seconds': round(wall, 3),
              'pricing_date': '2026-09-06', 'rates_per_million_usd': RATES,
              'billing_note': 'API usage x standard paid rates; not an invoice. Free tier, credits, taxes excluded. Missing usage is unknown, not zero.'}
    (folder/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Gemini 동일 입력 10쌍 원고 비교', '',
        '실제 수집이 아닌 합성 관측 소재. 현재 전체 작문 템플릿과 아래 명시적 페르소나를 사용했다. DB 예시·최근 게시글·댓글 타겟은 제외했다.', '',
        '두 모델에 같은 system/prompt/schema/temperature/max tokens를 전달했으며 쌍별 해시를 확인한다. 서버 난수는 통제하지 않는다. 2.5는 기존 어댑터의 thinkingBudget=0, 3.1은 서버 기본 추론 설정이다.', '',
        '원고 생성만 20건인 비교 실험으로, 실제 운영의 상시 소재 10% 배분을 재현한 것이 아니다. 자동 게시·품질 합격 판정은 없다.', '',
        '비용은 [Google 공식 일반 유료 단가](https://ai.google.dev/gemini-api/docs/pricing) × 실제 응답 사용량이며, 추론 출력과 캐시 할인도 포함한다. 무료 구간·크레딧·세금과 청구서 확정액은 확인하지 않았다.', '',
        '| 모델 | 정상/시도 | 입력 | 출력 | 추론 | 캐시 | API 시간(초) | 계산 비용(USD) |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for m, s in summaries.items():
        lines.append(f"| {m} | {s['ready']}/{s['attempts']} | {s['input_tokens']} | {s['output_tokens']} | {s['thinking_tokens']} | {s['cached_tokens']} | {s['api_seconds']} | ${s['cost_usd']} |")
    lines += ['', f'총 계산 비용: **${total}**. 대기 포함 전체 실행: {wall:.3f}초.', '']
    for i, (tone, source) in enumerate(CASES, 1):
        pair = [r for r in rows if r['case'] == i]
        if not pair:
            continue
        lines += [f'## {i:02d}. {pair[0]["persona_name"]} · {tone}', '', f'소재: {source}', '',
                  f'페르소나: {pair[0]["persona_profile"]["vocab_style"]}', '',
                  f'쌍별 요청 해시 동일: {len(pair) == 2 and pair[0]["request_sha256"] == pair[1]["request_sha256"]}', '']
        for r in pair:
            draft = r['draft']
            lines += [f'### {r["model"]}', '', f'제목: {draft.get("title", "")}', '',
                      f'본문: {draft.get("content", "")}', '',
                      f'정상 파싱: {r["ready"]} · API {r["api_seconds"]:.3f}초 · ${r["cost_usd"]}', '']
            if r['error']:
                lines += [f'오류 유형: {r["error"]}', '']
    (folder/'comparison.md').write_text('\n'.join(lines), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-paid', action='store_true')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if not args.run_paid:
        parser.error('--run-paid is required; at most 20 billable calls')
    os.chdir(ROOT)
    load_dotenv(ROOT/'.env')
    key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY', '')
    if not key:
        raise SystemExit('API key not configured')
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    names = {p['key']: p['name'] for p in pm.load_json('personas.json')}
    profiles = pm.load_json('persona_profiles.json')
    tones = pm.load_json('tones.json')
    assert all(t in names and t in profiles and t in tones for t, _ in CASES)
    rows, start = [], time.perf_counter()
    for i, (tone, source) in enumerate(CASES, 1):
        reference = None
        for model in RATES:
            random.seed(2026090600+i)
            capture = Capture(GeminiClient(api_key=key, model=model))
            brain = GhostBrain(provider=capture, model_name=model)
            brain._get_style_examples = lambda *a, **kw: []
            draft, error = {}, ''
            try:
                draft = brain.generate_post('합성 테스트 소재(현재 유행이나 실시간 관측이 아님): '+source,
                    'universe', tone=tone, context_hours=0, recent_posts=[],
                    length='짧게 (1~2문장)', expected_slot='G')
            except Exception as exc:
                error = type(exc).__name__
            request = capture.request or {}
            digest = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if reference is None:
                reference = digest
            assert digest == reference, 'Paired request mismatch'
            usage = capture.response.usage if capture.response else {}
            row = {'case': i, 'model': model, 'model_version': capture.response.model if capture.response else '',
                   'timestamp': datetime.now(timezone.utc).isoformat(), 'tone': tone, 'persona_name': names[tone],
                   'persona_profile': profiles[tone], 'tone_instruction': tones[tone], 'source': source,
                   'request_sha256': digest, 'request': request, 'usage': usage,
                   'raw_response': capture.response.text if capture.response else '', 'draft': draft,
                   'ready': bool(draft.get('title') and draft.get('content') and not draft.get('_parse_error')),
                   'error': error, 'api_seconds': round(capture.elapsed, 3), 'cost_usd': str(cost_usd(model, usage))}
            rows.append(row)
            (folder/f'{i:02d}-{model}.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
            summary = report(rows, folder, time.perf_counter()-start)
            print(json.dumps({k: row[k] for k in ('case','model','ready','api_seconds','cost_usd','error')}), flush=True)
            if error or not row['ready']:
                raise SystemExit('Stopped on failure; no automatic retry; inspect saved evidence')
            time.sleep(1.5)
    summary = report(rows, folder, time.perf_counter()-start)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
