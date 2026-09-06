"""Five-space editorial UI. User actions cross StudioService; rendering is read-only."""
from decimal import Decimal
import html
import json
import os
from pathlib import Path
import streamlit as st
from ghost_protocol import prompt_manager as pm
from .policy import MODELS, STAGES, source_ready, analysis_ready
from .service import StudioService

ROOT = Path(__file__).resolve().parents[2]
NAV = ['작업실','페르소나·규칙','실험실','운영 기록','설정']


@st.cache_resource
def get_service(directory):
    return StudioService(directory)


def esc(value):
    return html.escape(str(value))


def empty(title, body):
    st.markdown(f'<div class="studio-empty"><h3>{esc(title)}</h3><p>{esc(body)}</p></div>', unsafe_allow_html=True)


def paper(title, body, meta=''):
    st.markdown(f'<article class="studio-paper"><div class="meta">{esc(meta)}</div><h3>{esc(title)}</h3><p>{esc(body)}</p></article>', unsafe_allow_html=True)


def run_action(fn):
    try:
        result = fn()
        st.session_state['studio_notice'] = '저장했습니다.'
        return result
    except (ValueError, KeyError) as exc:
        st.error(str(exc))
        return None


def money(calls):
    known = sum((Decimal(c['cost_usd']) for c in calls if c.get('cost_usd') is not None), Decimal(0))
    return f'${known:.5f}' + (' + 미확인' if any(c.get('cost_usd') is None for c in calls) else '')


def launch(service, work, action, payload):
    job = run_action(lambda:service.start(work['id'],action,payload))
    if job:
        st.session_state['studio_job'] = job
        st.rerun()


@st.fragment(run_every=2)
def progress(service):
    job = service.busy()
    if job:
        st.progress(job['progress']/max(1,job['total']), text=f"{job['action']} · {job['progress']}/{job['total']} 진행 중")
        st.caption('다른 화면을 살펴봐도 작업은 계속됩니다. 중단은 현재 요청이 끝난 뒤 적용됩니다.')
        if st.button('현재 작업 중단', key='studio_cancel'):
            service.cancel(job['id'])
            st.info('중단을 요청했습니다. 이미 받은 결과는 보존합니다.')
        st.session_state['studio_job'] = job['id']
    elif st.session_state.get('studio_job'):
        finished = service.job(st.session_state.pop('studio_job'))
        if finished:
            st.session_state['studio_notice'] = '작업 완료' if finished['status']=='done' else finished.get('error') or '작업 중단'
            st.session_state.pop('studio_step',None)
            st.rerun()


def choose_work(service):
    works = service.workspaces()
    by_id = {w['id']:w for w in works}
    selected = st.query_params.get('work') or st.session_state.get('studio_work')
    picker, creator = st.columns([3,1],vertical_alignment='bottom') if works else (st.container(),st.container())
    if works:
        selected = selected if selected in by_id else works[0]['id']
        selected = picker.selectbox('현재 작업',list(by_id),index=list(by_id).index(selected),
            format_func=lambda id:by_id[id]['name'],key='studio_work_selector')
        st.session_state['studio_work'] = selected
        st.query_params['work'] = selected
    with creator.expander('새 작업 만들기', expanded=not works):
        with st.form('new_workspace'):
            name = st.text_input('작업 이름',placeholder='예: 우주 갤러리 · 저녁 원고')
            a,b = st.columns([2,1])
            gallery = a.text_input('게시판 ID',value='universe')
            kind = b.selectbox('게시판 종류',['board','mgallery','mini'],format_func=lambda s:{'board':'정규','mgallery':'마이너','mini':'미니'}[s])
            if st.form_submit_button('작업 만들기',type='primary'):
                w = run_action(lambda:service.create_workspace(name,gallery,kind))
                if w:
                    st.session_state.pop('studio_work_selector',None)
                    st.session_state.pop('studio_step',None)
                    st.session_state['studio_work'] = w['id']
                    st.query_params['work'] = w['id']
                    st.rerun()
    return service.workspace(selected) if selected else None


def source_page(service, work):
    st.subheader('이번 원고의 출발점을 정하세요')
    st.caption('직접 자료를 넣거나 저장된 자료를 읽습니다. 새 수집은 별도로 실행해야 합니다.')
    raw = work['source']
    if raw and not source_ready(raw):
        st.error('수집 중단 · ' + str(raw.get('source_access',{}).get('reason','자료 없음')) + ' — 원본 확인 전 분석하지 않습니다.')
    with st.form('source_'+work['id']):
        text = st.text_area('원본 자료 · 한 줄에 한 소재',value='\n'.join(raw.get('titles',[])),height=220,
                            placeholder='글 제목이나 관측 사실을 붙여 넣으세요. 개인 식별 정보는 제외하세요.')
        st.caption('자료를 바꾸면 분석을 다시 확인해야 하며, 기존 원고의 승인은 해제됩니다.')
        if st.form_submit_button('자료 저장',type='primary',disabled=bool(service.busy())):
            if run_action(lambda:(service.save_source(work['id'],text),True)[1]):
                st.session_state.pop('studio_step',None)
                st.rerun()
    with st.expander('저장된 자료 / 보호 수집'):
        st.caption('기존 DB는 읽기 전용입니다. 보호 수집은 최대 3페이지·원문6개·글당댓글3개이며 로그인하지 않습니다.')
        if st.button('기존 DB 자료 불러오기',disabled=bool(service.busy())):
            launch(service,work,'stored',{})
        pages = st.number_input('목록 페이지',1,3,service.settings()['pages'])
        consent = st.checkbox('이 게시판에 새 읽기 요청을 보내겠습니다.')
        if st.button('보호 수집 시작',disabled=bool(service.busy()) or not consent):
            launch(service,work,'collect',{'pages':pages})
    if raw:
        with st.expander('원본 스냅샷 확인'):
            st.json(raw)


def analysis_page(service, work):
    if not source_ready(work['source']):
        empty('먼저 자료를 준비하세요','자료 준비 단계에서 저장하거나, 차단 원인을 확인하세요.')
        return
    left,right = st.columns([1,1.35],gap='large')
    with left:
        st.subheader('수집 근거')
        st.caption(work['source'].get('origin','보호 수집 자료') + ' · ' + str(len(work['source']['titles']))+'개 소재')
        with st.container(height=390,border=True):
            for line in work['source']['titles'][:60]:
                st.write(line)
                st.divider()
    with right:
        st.subheader('분석을 확인하고 작문 방향을 정하세요')
        a = work['analysis']
        if a.get('_parse_error'):
            st.error('분석 응답 파싱 실패. 원본 응답을 확인하세요. 자동 초안은 만들지 않습니다.')
            with st.expander('실패한 원본 응답'):
                st.code(a.get('_raw_response','응답 없음'),language=None)
        if analysis_ready(a):
            with st.form('analysis_'+work['id']):
                summary = st.text_area('분석 요약',value=a.get('summary',''),height=125)
                guidance = st.text_area('이번 작문 지시',value=a.get('generation_guidance',''),height=165)
                if st.form_submit_button('분석 확인 · 원고 제작으로',type='primary',disabled=bool(service.busy())):
                    if run_action(lambda:(service.confirm_analysis(work['id'],summary,guidance),True)[1]):
                        st.session_state.pop('studio_step',None)
                        st.rerun()
        else:
            st.info('자료를 선택한 API 모델로 분석합니다. 아직 분석하지 않았습니다.')
        consent = st.checkbox('자료를 Google API로 보내 분석합니다. 사용량이 발생할 수 있습니다.',key='analysis_consent')
        if st.button('자료 분석' if not a else '분석 다시 실행',disabled=not consent or bool(service.busy())):
            launch(service,work,'analyze',{})


def draft_controls(service, work, compare=False):
    if not analysis_ready(work['analysis']):
        empty('분석을 먼저 확인하세요','자료가 비어 있거나 분석에 실패한 상태에서는 원고를 생성하지 않습니다.')
        return
    if not work['analysis'].get('confirmed'):
        st.info('분석 확인 단계에서 요약과 작문 지시를 확인한 뒤 원고를 만드세요.')
        return
    names = {p['key']:p['name'] for p in pm.load_json('personas.json')}
    st.subheader('같은 소재, 다른 반응' if compare else '누구의 시선으로 쓸까요?')
    st.caption('기존 전체 작문 프롬프트와 선택 페르소나를 전달합니다. 댓글 대상은 만들지 않습니다.')
    with st.form('draft_controls_'+str(compare)):
        tones = st.multiselect('사용할 페르소나',list(names),default=['cynical','neutral','analytical'],format_func=lambda k:names[k])
        topic = st.text_area('집중할 소재 · 비우면 원본 소재를 순서대로 사용',placeholder='원본에서 주목할 장면이나 사실을 적으세요.',height=95)
        count = st.number_input('모델당 원고 수' if compare else '만들 원고 수',1,service.settings()['max_drafts'],min(3,service.settings()['max_drafts']))
        st.caption('비교는 두 모델에 같은 입력과 페르소나를 줍니다. 모델의 서버 난수는 통제하지 않습니다.' if compare else '선택한 페르소나를 순서대로 배정합니다. 추가 규칙은 페르소나·규칙에서 확인하세요.')
        paid = st.checkbox('이번 생성의 API 사용량 발생에 동의합니다.')
        go = st.form_submit_button('두 모델 비교 실행' if compare else '원고 생성',type='primary',disabled=bool(service.busy()))
        if go:
            if not paid:
                st.error('API 사용량 동의를 확인하세요.')
            else:
                launch(service,work,'compare' if compare else 'generate',{'tones':tones,'count':count,'topic':topic})


def review_page(service, work):
    drafts = work['drafts']
    if not drafts:
        empty('원고가 놓일 자리입니다','원고 제작에서 페르소나와 개수를 정하거나, 실험실의 기존 20개 원고로 검토해 보세요.')
        return
    selection, filters = st.columns([2,1.25],gap='large',vertical_alignment='bottom')
    filt = filters.radio('원고 필터',['전체','검토 대기','승인됨'],horizontal=True)
    drafts = [d for d in drafts if filt=='전체' or (d.get('approved_revision')==d['revision'])==(filt=='승인됨')]
    if not drafts:
        st.info('이 조건의 원고가 없습니다.')
        return
    names = {p['key']:p['name'] for p in pm.load_json('personas.json')}
    chosen = selection.selectbox('검토할 원고', [d['id'] for d in drafts],format_func=lambda id:next(f"{i+1:02d} · {d['title'] or '실패한 원고'} · {d['model']}" for i,d in enumerate(drafts) if d['id']==id))
    d = next(d for d in drafts if d['id']==chosen)
    left,right = st.columns([1.5,1],gap='large')
    with left:
        paper(d['title'],d['content'],names.get(d['tone'],d['tone'])+' / '+d['model']+f" / v{d['revision']}")
        buffer_key = 'edit_buffer_'+d['id']+'_'+str(d['revision'])
        buffer = st.session_state.setdefault(buffer_key, {'title':d['title'],'content':d['content']})
        title_key, body_key = buffer_key+'_title', buffer_key+'_body'
        def buffer_change():
            st.session_state[buffer_key] = {'title':st.session_state[title_key], 'content':st.session_state[body_key]}
        def save_edit():
            run_action(lambda:service.save_draft(work['id'],d['id'],st.session_state[title_key],st.session_state[body_key],expected_revision=d['revision']))
        with st.container(border=True):
            title = st.text_input('제목 수정',value=buffer['title'],key=title_key,on_change=buffer_change)
            content = st.text_area('본문 수정',value=buffer['content'],height=180,key=body_key,on_change=buffer_change)
            dirty = title != d['title'] or content != d['content']
            if dirty:
                st.warning('저장하지 않은 편집이 있습니다. 메뉴 이동 중에는 유지되지만 새로고침 전에 저장하세요.')
            st.caption('수정 저장 시 이전 승인이 해제됩니다. 승인은 저장한 버전에만 적용됩니다.')
            st.button('수정 저장',type='primary',disabled=bool(service.busy()),on_click=save_edit)
    with right:
        st.subheader('원고 옆의 근거')
        st.write(d.get('source_topic',''))
        st.caption('페르소나: '+names.get(d['tone'],d['tone']))
        st.write(pm.load_json('persona_profiles.json').get(d['tone'],{}).get('vocab_style',''))
        for warning in d.get('warnings',[]):
            st.warning(warning)
        if d.get('stale_source'):
            st.error('자료 변경 전 원고입니다. 새 자료로 다시 생성하세요.')
        with st.expander('생성 원문 / 제외된 댓글'):
            st.json(d.get('raw',{}))
        checked = st.checkbox('저장된 원고의 사실·말투·게시 대상을 확인했습니다.',key='approve_'+d['id']+'_'+str(d['revision']))
        def approve():
            run_action(lambda:service.approve_draft(work['id'],d['id'],checked=checked,expected_revision=d['revision']))
        st.button('이 버전 승인',disabled=dirty or not checked or bool(service.busy()) or d.get('failed',False) or d.get('stale_source',False),on_click=approve)
        if d.get('approved_revision')==d['revision']:
            st.success('현재 저장 버전 승인됨 · 아직 게시하지 않았습니다.')


def approval_page(service, work):
    try:
        packet = service.export_approved(work['id'])
    except ValueError:
        empty('검토한 원고만 이곳에 모입니다','비교·수정 단계에서 사실과 페르소나를 확인하고 현재 버전을 승인하세요.')
        return
    st.subheader(f"승인한 원고 {len(packet['drafts'])}개")
    st.info('승인은 게시가 아닙니다. 이 화면은 외부 게시 버튼을 자동으로 누르지 않습니다.')
    for d in packet['drafts']:
        paper(d['title'],d['content'],f"{work['gallery']} · v{d['revision']} · 승인됨")
    markdown = '\n\n---\n\n'.join(f"# {d['title']}\n\n{d['content']}" for d in packet['drafts'])
    a,b = st.columns(2)
    a.download_button('승인 원고 Markdown 저장',markdown,file_name='approved-drafts.md',mime='text/markdown')
    b.download_button('승인 패키지 JSON 저장',json.dumps(packet,ensure_ascii=False,indent=2),file_name='approved-drafts.json',mime='application/json')
    from ghost_protocol.config import get_write_url
    st.link_button('게시판 글쓰기 직접 열기',get_write_url(work['gallery_type'],work['gallery']))
    st.caption('직접 게시 전 게시판·계정·내용을 다시 확인하세요. 자동 운영은 운영 기록의 기존 콘솔에서 별도로 실행합니다.')


def workbench(service):
    work = choose_work(service)
    if not work:
        empty('자료에서 원고까지, 한 작업씩','작업 이름과 게시판을 정하면 자료 준비부터 시작합니다. 기존 자료와 원고는 그대로 보존됩니다.')
        return
    st.markdown(f'<div class="studio-context"><span>게시판 <strong>{esc(work["gallery"])}</strong></span><span>모델 <strong>{esc(service.settings()["model"])}</strong></span><span>새 API 호출 <strong>{money(service.calls(work["id"]))}</strong></span></div>',unsafe_allow_html=True)
    stage_keys = list(STAGES)
    label_map = {key:f'{i+1} {value}' for i,(key,value) in enumerate(STAGES.items())}
    key = 'step_'+work['id']
    seen_key = 'stage_seen_'+work['id']
    last_key = 'last_step_'+work['id']
    if st.session_state.get(seen_key) != work['stage']:
        st.session_state[key] = work['stage']
        st.session_state[seen_key] = work['stage']
    elif not st.session_state.get(key):
        st.session_state[key] = st.session_state.get(last_key,work['stage'])
    step = st.radio('작업 단계',stage_keys,index=None,format_func=label_map.get,horizontal=True,key=key)
    st.session_state[last_key] = step
    st.caption('단계는 자유롭게 살펴볼 수 있습니다. 실행은 자료·분석·승인 조건이 갖춰졌을 때만 가능합니다.')
    {'source':source_page,'analysis':analysis_page,'draft':draft_controls,'review':review_page,'approval':approval_page}[step](service,work)


def personas(service):
    st.title('말투보다, 바라보는 방식')
    st.caption('기존 페르소나와 전체 작문 템플릿을 보존합니다. 운영자 추가 규칙만 별도 버전으로 저장합니다.')
    items = pm.load_json('personas.json')
    names = {p['key']:p['name'] for p in items}
    tone = st.selectbox('페르소나',list(names),format_func=names.get)
    profile = pm.load_json('persona_profiles.json')[tone]
    left,right = st.columns([1,1.2],gap='large')
    with left:
        paper(names[tone],profile['vocab_style'],tone)
        st.write('좋은 반응')
        for move in profile.get('good_moves',[]):
            st.write('· '+move)
        st.write('피할 표현: '+', '.join(profile.get('never_say',[])))
        with st.expander('원본 페르소나 전체'):
            st.json(profile)
    with right:
        settings = service.settings()
        with st.form('rules_'+tone):
            notes = st.text_area('이 페르소나의 추가 작문 규칙',value=settings['persona_notes'].get(tone,''),height=170)
            common = st.text_area('모든 원고의 추가 작문 규칙',value=settings['rules'],height=130)
            st.caption('새 생성부터 적용합니다. 기존 원고와 원본 파일은 바뀌지 않습니다.')
            if st.form_submit_button('추가 규칙 저장',type='primary',disabled=bool(service.busy())):
                settings['persona_notes'][tone] = notes
                if run_action(lambda:(service.save_settings({'rules':common,'persona_notes':settings['persona_notes']}),True)[1]):
                    st.success('추가 규칙을 저장했습니다.')
    with st.expander('전체 작문 프롬프트 · 축약 없음'):
        st.code(pm.load('generate_post.txt'),language=None)
    with st.expander('규칙 저장 이력'):
        revisions = service.store.list('settings_revision')
        st.write(f'보존된 설정 버전 {len(revisions)}개')
        for r in revisions[:10]:
            st.caption(r.get('saved',''))
            st.json({'rules':r['rules'],'persona_notes':r['persona_notes']},expanded=False)


def lab(service):
    st.title('차이를 보고 고르세요')
    st.caption('같은 입력의 원고를 나란히 읽습니다. 파싱 성공과 원고 품질을 구분합니다.')
    pairs = service.benchmark_pairs()
    if pairs:
        st.markdown('<div class="studio-kicker">보존된 실험 · 2026.09.06 / 합성 소재</div>',unsafe_allow_html=True)
        st.caption('각 모델 10개 · 합계 $0.04008768 · 87.01초 / 당시 API 사용량과 공식 단가 계산액. 새 호출 없음.')
        idx = st.selectbox('비교할 소재',range(len(pairs)),format_func=lambda i:f"{i+1:02d} · {pairs[i]['rows'][0]['persona_name']}")
        pair = pairs[idx]
        st.write(pair['rows'][0]['source'])
        cols = st.columns(2,gap='large')
        for col,row in zip(cols,pair['rows']):
            with col:
                paper(row['draft']['title'],row['draft']['content'],row['model'])
                st.caption(f"{row['api_seconds']}초 · ${row['cost_usd']} · 요청/페르소나 동일")
        st.warning('이 실험에는 원본에 없는 사실·임의 댓글 대상·페르소나 미준수가 있습니다. 게시 가능 판정이 아닙니다.')
        if st.button('기존 원고 20개를 작업실로 가져오기',disabled=bool(service.busy())):
            work = run_action(service.import_benchmark)
            if work:
                st.session_state['studio_work'] = work['id']
                st.session_state.pop('studio_work_selector',None)
                st.query_params.update({'view':'작업실','work':work['id']})
                st.session_state['studio_next_view'] = '작업실'
                st.rerun()
    with st.expander('현재 작업으로 새 비교 실행'):
        works = service.workspaces()
        if not works:
            st.info('작업실에서 자료와 분석을 준비하세요.')
        else:
            wid = st.selectbox('비교 작업',[w['id'] for w in works],format_func=lambda id:next(w['name'] for w in works if w['id']==id))
            draft_controls(service,service.workspace(wid),compare=True)
    comparison_jobs = [j for j in service.jobs() if j['action']=='compare']
    if comparison_jobs:
        st.subheader('새 비교 결과')
        j = st.selectbox('비교 실행 기록',[j['id'] for j in comparison_jobs])
        job = service.job(j)
        work = service.workspace(job['workspace_id'])
        for pair_no in sorted({d['pair'] for d in work['drafts'] if d['job_id']==j}):
            ds = [d for d in work['drafts'] if d['job_id']==j and d['pair']==pair_no]
            for col,d in zip(st.columns(2),ds):
                with col:
                    paper(d['title'],d['content'],d['model'])


def history(service):
    st.title('작업의 흔적')
    st.caption('진행·실패·비용을 실제 기록으로 확인합니다. 미실행은 정상으로 표시하지 않습니다.')
    calls = service.calls()
    a,b,c = st.columns(3)
    a.metric('저장된 작업',len(service.workspaces()))
    b.metric('API 응답 기록',len(calls))
    c.metric('계산 비용',money(calls))
    st.caption('API 사용량 × 2026-09-06 일반 유료 단가. 청구서 확정액 아님. 과거 비교실험 비용은 별도입니다.')
    jobs = service.jobs()
    if not jobs:
        empty('아직 실행 기록이 없습니다','수집·자료 불러오기·API 작업을 실행하면 이곳에서 확인할 수 있습니다. 원고 수정은 별도 버전으로 보존합니다.')
    for j in jobs[:30]:
        with st.expander(f"{j['created']} · {j['action']} · {j['status']} · {j['progress']}/{j['total']}"):
            if j.get('error'):
                st.error(j['error'])
            for log in j['logs']:
                st.text(log['at']+' '+log['message'])
    with st.expander('호출별 사용량·실제 전달 프롬프트'):
        for i,call in enumerate(calls[:50]):
            with st.expander(f"{i+1} · {call['model']} · {call['seconds']}초 · ${call.get('cost_usd') or '미확인'}"):
                st.json(call)
    st.divider()
    st.subheader('고급 운영 · 기존 콘솔')
    st.caption('무한 실행·리허설·자동 게시·댓글 감시는 기존 운영 콘솔에 보존했습니다. 새 작업실 승인과 자동으로 연결되지 않습니다.')
    st.caption('기존 콘솔과 새 작업실의 외부 작업을 동시에 실행하지 마세요. 두 실행 큐는 공유하지 않습니다.')
    st.link_button('기존 운영 콘솔 열기','?legacy=1')


def settings_page(service):
    st.title('필요한 설정만, 분명하게')
    settings = service.settings()
    configured = bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))
    if configured:
        st.success('API 키 설정됨 · 실제 연결/할당량은 작업 실행 시 확인합니다.')
    else:
        st.error('API 키 없음 · 로컬 .env에 GEMINI_API_KEY를 설정한 뒤 앱을 다시 시작하세요.')
    with st.form('studio_settings'):
        model = st.selectbox('기본 생성·분석 모델',MODELS,index=MODELS.index(settings['model']))
        a,b,c = st.columns(3)
        gap = a.number_input('호출 사이 대기(초)',1.5,30.0,float(settings['gap']),.5)
        limit = b.number_input('한 번에 만들 원고 상한',1,10,settings['max_drafts'])
        pages = c.number_input('기본 수집 페이지',1,3,settings['pages'])
        if st.form_submit_button('설정 저장',type='primary',disabled=bool(service.busy())):
            if run_action(lambda:(service.save_settings({'model':model,'gap':gap,'max_drafts':limit,'pages':pages}),True)[1]):
                st.success('저장했습니다. 다음 작업부터 적용됩니다.')
    st.subheader('변하지 않는 안전 규칙')
    st.write('수집 최대 3페이지 · 원문 6개 · 글당 댓글 3개. 빈 응답/차단이면 즉시 중단합니다.')
    st.write('외부 게시 자동 실행 없음 · 승인 후 수정하면 재승인 필요 · 추가 API 자동 재시도 없음.')
    st.caption('기존 페르소나·프롬프트·DB·계정 세션은 보존합니다. 키는 브라우저나 새 DB에 저장하지 않습니다.')
    st.code('data/studio/studio.sqlite3',language=None)
    st.caption('새 작업·수정·승인은 로컬 SQLite에 저장됩니다. 기존 data/ghost_protocol.db는 그대로 둡니다.')


def render_studio():
    st.set_page_config(page_title='Ghost Protocol · Studio',page_icon='◌',layout='wide',initial_sidebar_state='collapsed')
    st.markdown('<style>'+Path(__file__).with_name('studio.css').read_text(encoding='utf-8')+'</style>',unsafe_allow_html=True)
    service = get_service(os.getenv('STUDIO_DATA_DIR',str(ROOT/'data/studio')))
    st.markdown('<header class="studio-mast"><div class="studio-brand">Ghost Protocol<small>EDITORIAL STUDIO</small></div><div class="studio-local"><b>● 로컬 작업실</b><br>원고는 이 컴퓨터에 보관됩니다</div></header>',unsafe_allow_html=True)
    initial = st.query_params.get('view','작업실')
    if 'studio_next_view' in st.session_state:
        st.session_state['studio_view'] = st.session_state.pop('studio_next_view')
    if 'studio_view' not in st.session_state:
        st.session_state['studio_view'] = initial if initial in NAV else '작업실'
    view = st.radio('공간',NAV,index=None,horizontal=True,label_visibility='collapsed',key='studio_view')
    st.query_params['view'] = view
    if notice := st.session_state.pop('studio_notice',None):
        st.info(notice)
    progress(service)
    if view=='작업실':
        if not service.workspaces():
            st.markdown('<div class="studio-kicker">WORKSPACE / 원고 제작</div>',unsafe_allow_html=True)
            st.title('다음 원고를 시작할까요?')
        workbench(service)
    else:
        {'페르소나·규칙':personas,'실험실':lab,'운영 기록':history,'설정':settings_page}[view](service)
