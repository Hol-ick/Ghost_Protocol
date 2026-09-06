"""Durable Studio commands. Streamlit never owns worker execution or approval."""
from pathlib import Path
from uuid import uuid4
import re
import copy
import json
import random
import threading
import time
from .policy import MODELS, analysis_ready, cost, draft_warnings
from .opinion_packet import build_opinion_packet, is_board_collection
from .store import StudioStore, now


class StudioService:
    def __init__(self, directory, backend=None):
        self.store = StudioStore(directory)
        if backend is None:
            from .adapters import StudioBackend
            backend = StudioBackend()
        self.backend = backend
        self._lock = threading.RLock()
        self._threads = {}
        self._cancel = {}
        for job in self.store.list('job'):
            if job['status'] in ('running', 'queued'):
                job.update(status='interrupted', error='프로세스 재시작으로 중단됨. 자동 재실행하지 않았습니다.')
                self.store.put('job', job['id'], job)

    def create_workspace(self, name, gallery, gallery_type='board'):
        if not name.strip() or not re.fullmatch(r'[A-Za-z0-9_]+', gallery):
            raise ValueError('영문/숫자/밑줄 게시판 ID를 입력하세요.')
        if gallery_type not in ('board', 'mgallery', 'mini'):
            raise ValueError('게시판 종류를 확인하세요.')
        work = {'id': uuid4().hex, 'name': name.strip()[:120], 'gallery': gallery, 'gallery_type': gallery_type,
                'stage': 'source', 'source': {}, 'analysis': {}, 'drafts': [], 'created': now(), 'updated': now()}
        self.store.put('workspace', work['id'], work)
        return work

    def workspace(self, id):
        work = self.store.get('workspace', id)
        if not work:
            raise ValueError('작업을 찾을 수 없습니다.')
        return work

    def workspaces(self):
        return self.store.list('workspace')

    def settings(self):
        return {'model': MODELS[0], 'gap': 1.5, 'max_drafts': 10, 'pages': 1,
                'rules': '', 'persona_notes': {}, **(self.store.get('settings','main') or {})}

    def save_settings(self, values):
        with self._lock:
            if self.busy():
                raise ValueError('작업이 끝난 뒤 설정을 저장하세요.')
            current = self.settings()
            current.update({k:v for k,v in values.items() if k in current})
            if current['model'] not in MODELS:
                raise ValueError('지원하는 모델을 선택하세요.')
            current['gap'] = max(1.5, min(30.0, float(current['gap'])))
            current['pages'] = max(1, min(3, int(current['pages'])))
            current['max_drafts'] = max(1, min(10, int(current['max_drafts'])))
            self.store.put('settings_revision', uuid4().hex, {**current, 'saved':now()})
            self.store.put('settings', 'main', current)

    def _save(self, work):
        work['updated'] = now()
        self.store.put('workspace', work['id'], work)

    def busy(self):
        return next((j for j in self.store.list('job') if j['status'] in ('queued','running')), None)

    def jobs(self):
        return self.store.list('job')

    def job(self, id):
        return self.store.get('job', id)

    def calls(self, workspace_id=None):
        return [c for c in self.store.list('call') if not workspace_id or c['workspace_id'] == workspace_id]

    def _editable(self):
        if self.busy():
            raise ValueError('진행 중인 작업이 있습니다. 완료 또는 중단 후 수정하세요.')

    def _set_source(self, work, source):
        if work['source']:
            self.store.put('source_revision', uuid4().hex, {'workspace_id':work['id'], 'source':work['source'], 'analysis':work['analysis']})
        work['source'] = source
        work['analysis'] = {}
        work['stage'] = 'analysis' if is_board_collection(source) else 'source'
        for d in work['drafts']:
            d['approved_revision'] = None
            d['stale_source'] = True
        self._save(work)

    def confirm_analysis(self, id):
        with self._lock:
            self._editable()
            work = self.workspace(id)
            if not is_board_collection(work['source']) or not analysis_ready(work['analysis']):
                raise ValueError('정상 게시판 수집과 분석이 먼저 필요합니다.')
            work['analysis']['confirmed'] = True
            work['stage'] = 'draft'
            self._save(work)

    def save_draft(self, id, draft_id, title, content, *, expected_revision):
        with self._lock:
            self._editable()
            work = self.workspace(id)
            d = next(d for d in work['drafts'] if d['id'] == draft_id)
            if d['revision'] != expected_revision:
                raise ValueError('다른 편집이 먼저 저장됐습니다. 최신 원고를 다시 여세요.')
            if not title.strip():
                raise ValueError('제목을 입력하세요.')
            self.store.put('draft_revision', uuid4().hex, {'workspace_id':id, 'draft':d})
            d.update(title=title.strip(), content=content, revision=d['revision']+1, approved_revision=None)
            d['warnings'] = draft_warnings(d, d.get('source_topic',''))
            self._save(work)

    def approve_draft(self, id, draft_id, *, checked=False, expected_revision):
        with self._lock:
            self._editable()
            work = self.workspace(id)
            d = next(d for d in work['drafts'] if d['id'] == draft_id)
            if d['revision'] != expected_revision:
                raise ValueError('다른 편집이 먼저 저장됐습니다. 최신 원고를 다시 검토하세요.')
            if not checked or not d['title'] or d.get('failed') or d.get('stale_source'):
                raise ValueError('사실·페르소나·게시 대상을 검토한 현재 원고만 승인할 수 있습니다.')
            d.update(approved_revision=d['revision'], approved_at=now())
            work['stage'] = 'approval'
            self._save(work)

    def export_approved(self, id):
        work = self.workspace(id)
        drafts = [d for d in work['drafts'] if d.get('approved_revision') == d['revision'] and not d.get('stale_source') and not d.get('failed')]
        if not drafts:
            raise ValueError('승인한 최신 원고가 없습니다.')
        return {'workspace':work['name'], 'gallery':work['gallery'], 'gallery_type':work['gallery_type'],
                'status':'approved_not_published', 'drafts':[
                    {k:d[k] for k in ('id','title','content','tone','revision','approved_at')} for d in drafts]}

    def start(self, id, action, payload):
        if action not in ('collect','analyze','generate','compare'):
            raise ValueError('지원하지 않는 작업입니다.')
        with self._lock:
            self._editable()
            work = self.workspace(id)
            if action in ('analyze','generate','compare') and not is_board_collection(work['source']):
                raise ValueError('정상 게시판 수집 결과가 필요합니다.')
            if action in ('generate','compare') and not analysis_ready(work['analysis']):
                raise ValueError('분석 실패를 먼저 해결하세요. 자동 초안은 중단합니다.')
            if action in ('generate','compare') and not work['analysis'].get('confirmed'):
                raise ValueError('분석 요약과 작문 지시를 먼저 확인하세요.')
            if action in ('generate','compare'):
                if str(payload.get('topic') or '').strip():
                    raise ValueError('소재를 직접 입력할 수 없습니다. 수집된 게시판 여론으로만 생성합니다.')
                from ghost_protocol import prompt_manager as pm
                keys = {p['key'] for p in pm.load_json('personas.json')}
                if not payload.get('tones') or any(t not in keys for t in payload['tones']):
                    raise ValueError('등록된 페르소나를 선택하세요.')
            settings = self.settings()
            payload = copy.deepcopy(payload)
            payload['count'] = max(1,min(settings['max_drafts'],int(payload.get('count',1))))
            payload['pages'] = max(1,min(3,int(payload.get('pages',settings['pages']))))
            job = {'id':uuid4().hex, 'workspace_id':id, 'action':action, 'status':'queued',
                   'progress':0, 'total':payload['count']*(2 if action=='compare' else 1) if action in ('generate','compare') else 1,
                   'created':now(), 'logs':[], 'error':''}
            self.store.put('job', job['id'], job)
            self._cancel[job['id']] = threading.Event()
            thread = threading.Thread(target=self._run, args=(job, work, payload, settings), daemon=True)
            self._threads[job['id']] = thread
            thread.start()
            return job['id']

    def cancel(self, id):
        if id in self._cancel:
            self._cancel[id].set()

    def wait(self, id, timeout=15):
        self._threads[id].join(timeout)
        if self._threads[id].is_alive():
            raise TimeoutError('Worker still running')

    def _run(self, job, work, payload, settings):
        event = self._cancel[job['id']]
        def log(message):
            job['logs'].append({'at':now(), 'message':str(message)[:500]})
            self.store.put('job', job['id'], job)
        def meter(model, request, response, seconds, error=''):
            usage = response.usage if response else {}
            self.store.put('call', uuid4().hex, {'job_id':job['id'], 'workspace_id':work['id'],
                'model':model, 'usage':usage, 'cost_usd':cost(model,usage), 'seconds':seconds, 'created':now(),
                'request':request, 'response':response.text if response else '', 'error':error})
        job['status'] = 'running'
        log('작업 시작 — ' + job['action'])
        start = time.perf_counter()
        try:
            if job['action'] == 'collect':
                source = self.backend.collect(work, payload, log)
                with self._lock:
                    self._set_source(work, source)
                if not is_board_collection(source):
                    raise ValueError('수집 중단: ' + str(source.get('source_access',{}).get('reason') or '자료 없음'))
            elif job['action'] == 'analyze':
                analysis = self.backend.analyze(work, settings['model'], meter)
                # Confirmation is an operator decision, never a model-provided field.
                analysis['confirmed'] = False
                work['analysis'] = analysis
                self._save(work)
                if not analysis_ready(analysis):
                    raise ValueError('분석 파싱 실패 — 원본 응답을 확인하세요.')
                work['stage'] = 'analysis'
            else:
                models = MODELS if job['action']=='compare' else (settings['model'],)
                for index in range(payload['count']):
                    tone = payload['tones'][index % len(payload['tones'])]
                    opinion_packet = build_opinion_packet(work['source'], work['analysis'], index)
                    rules = '\n'.join(filter(None, [settings['rules'],settings['persona_notes'].get(tone,'')]))
                    for model in models:
                        if event.is_set():
                            break
                        random.seed(index+20260906)
                        result = self.backend.generate(work, model, tone, opinion_packet, rules, meter)
                        draft = {'id':uuid4().hex, 'title':result.get('title',''), 'content':result.get('content',''),
                                 'target_comments':[], 'tone':tone, 'model':model, 'source_topic':opinion_packet,
                                 'warnings':draft_warnings(result, opinion_packet), 'raw':result, 'revision':1,
                                 'approved_revision':None, 'failed':bool(result.get('_parse_error') or not result.get('title')),
                                 'job_id':job['id'], 'pair':index+1}
                        work['drafts'].append(draft)
                        work['stage'] = 'review'
                        self._save(work)
                        job['progress'] += 1
                        log(f"원고 {job['progress']}/{job['total']} · {model} · {tone}")
                        if draft['failed']:
                            raise ValueError('원고 파싱 실패 — 추가 생성 중단, 원본 응답 확인 필요')
                        if job['progress'] < job['total'] and event.wait(settings['gap']):
                            break
                    if event.is_set():
                        break
            self._save(work)
            job['status'] = 'cancelled' if event.is_set() else 'done'
            if job['status']=='done':
                job['progress'] = job['total']
        except Exception as exc:
            job['status'] = 'failed'
            job['error'] = str(exc)[:400] if isinstance(exc, ValueError) else f'{type(exc).__name__} — 연결/키/할당량을 확인하세요. 자동 재시도하지 않습니다.'
        finally:
            job['seconds'] = round(time.perf_counter()-start,3)
            log('작업 ' + job['status'])

    def benchmark_pairs(self):
        root = Path(__file__).resolve().parents[2] / 'docs/benchmarks/2026-09-06-gemini-10-pairs'
        rows = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(root.glob('*-gemini-*.json'))]
        return [{'case':i, 'rows':[r for r in rows if r['case']==i]} for i in sorted({r['case'] for r in rows})]

    def import_benchmark(self):
        with self._lock:
            self._editable()
            existing = next((w for w in self.workspaces() if w.get('fixture')=='gemini-10-pairs'),None)
            if existing:
                return existing
            pairs = self.benchmark_pairs()
            work = self.create_workspace('Gemini 비교 · 합성 원고 20개', 'universe')
            work['fixture'] = 'gemini-10-pairs'
            titles = [p['rows'][0]['source'] for p in pairs]
            work['source'] = {'titles':titles,'comments':[],'source_access':{'status':'ok'},'origin':'보존된 합성 비교실험'}
            work['analysis'] = {'summary':'기존 10쌍 비교용 합성 관측 소재입니다. 실제 게시판 분위기 분석이 아닙니다.', 'confirmed':True}
            for pair in pairs:
                for r in pair['rows']:
                    d = r['draft']
                    work['drafts'].append({'id':uuid4().hex, 'title':d['title'], 'content':d['content'], 'tone':r['tone'],
                        'model':r['model'],'source_topic':r['source'],'warnings':draft_warnings(d,r['source']),
                        'raw':d,'target_comments':[],'revision':1,'approved_revision':None,'failed':False,
                        'pair':pair['case'],'job_id':'benchmark', 'historical_cost_usd':r['cost_usd']})
            work['stage'] = 'review'
            self._save(work)
            return work
