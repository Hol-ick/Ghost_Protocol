"""Five-space editorial UI. User actions cross StudioService; rendering is read-only."""
from decimal import Decimal
import html
import json
import os
from pathlib import Path
import streamlit as st
from ghost_protocol import prompt_manager as pm
from .policy import MODELS, STAGES, analysis_ready
from .opinion_packet import is_board_collection
from .service import StudioService
from .presentation import is_approved, resume_step

ROOT = Path(__file__).resolve().parents[2]
NAV = ['작업실','페르소나·규칙','실험실','운영 기록','설정']


@st.cache_resource
def get_service(directory):
    return StudioService(directory)


def esc(value):
    return html.escape(str(value))


def empty(label):
    st.info(label)


def move_to(work, step):
    st.session_state['next_step_'+work['id']] = step


def step_button(work, step, label):
    def open_step():
        move_to(work,step)
        st.session_state['studio_view'] = '작업실'
        st.session_state['studio_next_work'] = work['id']
    st.button(label,on_click=open_step)


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
        if st.button('현재 작업 중단', key='studio_cancel',help='현재 요청이 끝난 뒤 중단'):
            service.cancel(job['id'])
            st.info('중단 요청됨')
        st.session_state['studio_job'] = job['id']
    elif st.session_state.get('studio_job'):
        finished = service.job(st.session_state.pop('studio_job'))
        if finished:
            if finished['status']=='done':
                st.session_state['studio_notice'] = '작업 완료'
            else:
                st.session_state['studio_error'] = finished.get('error') or '작업 중단'
            st.session_state.pop('studio_step',None)
            st.rerun()


def new_work_form(service, *, cancel=False):
    if st.session_state.get('studio_next_work'):
        st.rerun()  # A dialog fragment hands the newly created work to the full page.
    def create_work():
        gallery = st.session_state['new_work_gallery']
        w = run_action(lambda:service.create_workspace(gallery, gallery, st.session_state['new_work_kind']))
        if w:
            st.session_state['studio_work'] = w['id']
            st.session_state['studio_next_work'] = w['id']
            st.query_params['work'] = w['id']
    with st.form('new_workspace'):
        a,b = st.columns([3,2])
        a.text_input('게시판 ID',value='universe',key='new_work_gallery')
        b.selectbox('게시판 종류',['board','mgallery','mini'],key='new_work_kind',format_func=lambda s:{'board':'정규','mgallery':'마이너','mini':'미니'}[s])
        create,back = st.columns([1,1])
        create.form_submit_button('작업 만들기',type='primary',width='stretch',on_click=create_work)
        if cancel and back.form_submit_button('취소',width='stretch'):
            st.rerun()


@st.dialog('새 작업',width='medium')
def new_work_dialog(service):
    new_work_form(service,cancel=True)


def choose_work(service):
    works = service.workspaces()
    if not works:
        new_work_form(service)
        return None
    by_id = {w['id']:w for w in works}
    if pending := st.session_state.pop('studio_next_work',None):
        st.session_state['studio_work_selector'] = pending
        st.query_params['work'] = pending
    selected = st.query_params.get('work') or st.session_state.get('studio_work')
    selected = selected if selected in by_id else works[0]['id']
    with st.container(key='work_toolbar'):
        picker,creator = st.columns([6,1],vertical_alignment='bottom')
        selected = picker.selectbox('현재 작업',list(by_id),index=list(by_id).index(selected),
            format_func=lambda id:by_id[id]['name'],key='studio_work_selector')
        if creator.button('새 작업',width='stretch'):
            new_work_dialog(service)
    st.session_state['studio_work'] = selected
    st.query_params['work'] = selected
    return service.workspace(selected)


def source_page(service, work):
    raw = work['source']
    collected = is_board_collection(raw)
    if raw and not collected:
        reason = str(raw.get('source_access',{}).get('reason','')).strip()
        if reason:
            st.error('수집 중단 · ' + reason + ' — 원본 확인 전 분석하지 않습니다.')
        else:
            st.info('이전 원고 작업입니다. 새 수집부터 시작하세요.')
    with st.container(border=True):
        pages = st.number_input('목록 페이지',1,3,service.settings()['pages'])
        consent = st.checkbox('게시판 수집 동의')
        label = '다시 수집' if collected else '수집 시작'
        if st.button(label,type='primary',disabled=bool(service.busy()) or not consent):
            launch(service,work,'collect',{'pages':pages})
    if collected:
        st.caption(f"글 {len(raw.get('titles', []))} · 댓글 {len(raw.get('comments', []))} · 수집 결과만 분석에 사용")
        with st.expander('수집 결과'):
            st.json({'titles':raw.get('titles', []), 'comments':raw.get('comments', []),
                     'raw_posts':raw.get('raw_posts', [])})
    elif raw:
        with st.expander('수집 원본 로그'):
            st.json(raw)


def analysis_page(service, work):
    if not is_board_collection(work['source']):
        empty('수집 필요')
        step_button(work,'source','수집으로')
        return
    left,right = st.columns([1,1.35],gap='large')
    with left:
        st.subheader('수집 근거')
        st.caption(work['source'].get('origin','게시판 ID 보호 수집') + ' · ' + str(len(work['source']['titles']))+'개 소재')
        with st.container(height=min(390,max(110,len(work['source']['titles'])*85)),border=True):
            for line in work['source']['titles'][:60]:
                st.write(line)
                st.divider()
    with right:
        st.subheader('분석')
        a = work['analysis']
        if a.get('_parse_error'):
            st.error('분석 파싱 실패 · 원본 응답 확인 필요')
            with st.expander('실패한 원본 응답'):
                st.code(a.get('_raw_response','응답 없음'),language=None)
        if analysis_ready(a):
            with st.container(border=True):
                st.write(a.get('summary',''))
                if a.get('ai_analysis'):
                    st.write(a['ai_analysis'])
                if a.get('generation_guidance'):
                    st.write(a['generation_guidance'])
                def confirm():
                    if run_action(lambda:(service.confirm_analysis(work['id']),True)[1]):
                        move_to(work,'draft')
                st.button('분석 확인 · 원고 제작으로',type='primary',disabled=bool(service.busy()),on_click=confirm)
        consent = st.checkbox('Google API 전송·과금 동의',key='analysis_consent')
        if st.button('자료 분석' if not a else '분석 다시 실행',disabled=not consent or bool(service.busy())):
            launch(service,work,'analyze',{})


def draft_controls(service, work, compare=False):
    if not is_board_collection(work['source']) or not analysis_ready(work['analysis']):
        empty('분석 필요')
        step_button(work,resume_step(work),'자료·분석 확인')
        return
    if not work['analysis'].get('confirmed'):
        st.info('분석 확인 필요')
        step_button(work,'analysis','분석 확인')
        return
    names = {p['key']:p['name'] for p in pm.load_json('personas.json')}
    with st.form('draft_controls_'+str(compare)):
        tones = st.multiselect('사용할 페르소나',list(names),default=['cynical','neutral','analytical'],format_func=lambda k:names[k])
        count = st.number_input('모델당 원고 수' if compare else '만들 원고 수',1,service.settings()['max_drafts'],min(3,service.settings()['max_drafts']))
        paid = st.checkbox('Google API 전송·과금 동의')
        go = st.form_submit_button('두 모델 비교 실행' if compare else '원고 생성',type='primary',disabled=bool(service.busy()))
        if go:
            if not paid:
                st.error('API 사용량 동의를 확인하세요.')
            else:
                launch(service,work,'compare' if compare else 'generate',{'tones':tones,'count':count})


def review_page(service, work):
    drafts = work['drafts']
    if not drafts:
        empty('원고 없음')
        step_button(work,resume_step(work),'원고 준비')
        return
    selection, filters = st.columns([1.65,1],gap='medium',vertical_alignment='bottom')
    approved_count = sum(is_approved(d) for d in drafts)
    counts = {'전체':len(drafts),'검토 대기':len(drafts)-approved_count,'승인됨':approved_count}
    filter_key, saved_filter = 'review_filter_'+work['id'], 'review_filter_saved_'+work['id']
    if filter_key not in st.session_state:
        st.session_state[filter_key] = st.session_state.get(saved_filter,'전체')
    filt = filters.radio('원고 필터',list(counts),horizontal=True,
        format_func=lambda label:f'{label} {counts[label]}',key=filter_key)
    st.session_state[saved_filter] = filt
    drafts = [d for d in drafts if filt=='전체' or is_approved(d)==(filt=='승인됨')]
    if not drafts:
        st.info('원고 없음')
        if counts['승인됨']:
            step_button(work,'approval','승인 원고 보기')
        return
    names = {p['key']:p['name'] for p in pm.load_json('personas.json')}
    ids = [d['id'] for d in drafts]
    positions = {item['id']:i+1 for i,item in enumerate(work['drafts'])}
    choice_key, cursor_key = 'review_choice_'+work['id'], 'review_cursor_'+work['id']
    cursor = st.session_state.get(choice_key,st.session_state.get(cursor_key))
    if cursor not in ids:
        cursor = next((item['id'] for item in drafts if not is_approved(item) and not item.get('stale_source')),ids[0])
    st.session_state[choice_key] = cursor
    def select_draft(id):
        st.session_state[choice_key] = id
        st.session_state[cursor_key] = id
    def remember_choice():
        st.session_state[cursor_key] = st.session_state[choice_key]
    with selection.container(key='review_picker'):
        picker,prev,nxt = st.columns([4,1,1],vertical_alignment='bottom')
        chosen = picker.selectbox('검토할 원고',ids,key=choice_key,on_change=remember_choice,
            format_func=lambda id:next(f"{positions[id]:02d} · {d['title'] or '실패한 원고'}" for d in drafts if d['id']==id))
        idx = ids.index(chosen)
        prev.button('이전',disabled=idx==0,on_click=select_draft,args=(ids[max(0,idx-1)],),width='stretch')
        nxt.button('다음',disabled=idx==len(ids)-1,on_click=select_draft,args=(ids[min(len(ids)-1,idx+1)],),width='stretch')
    st.session_state[cursor_key] = chosen
    d = next(d for d in drafts if d['id']==chosen)
    left,right = st.columns([1.5,1],gap='large')
    with left:
        buffer_key = 'edit_buffer_'+d['id']+'_'+str(d['revision'])
        buffer = st.session_state.setdefault(buffer_key, {'title':d['title'],'content':d['content']})
        title_key, body_key = buffer_key+'_title', buffer_key+'_body'
        def buffer_change():
            st.session_state[buffer_key] = {'title':st.session_state[title_key], 'content':st.session_state[body_key]}
        def save_edit():
            ok = run_action(lambda:(service.save_draft(work['id'],d['id'],st.session_state[title_key],st.session_state[body_key],expected_revision=d['revision']),True)[1])
            if ok and is_approved(d):
                st.session_state[filter_key] = '검토 대기'
                select_draft(d['id'])
                move_to(work,'review')
        with st.container(border=True,key='draft_editor'):
            title = st.text_input('제목 수정',value=buffer['title'],key=title_key,on_change=buffer_change)
            content = st.text_area('본문 수정',value=buffer['content'],height=150,key=body_key,on_change=buffer_change)
            dirty = title != d['title'] or content != d['content']
            if dirty:
                st.markdown('<div class="studio-unsaved">미저장</div>',unsafe_allow_html=True)
            checked = st.checkbox('사실·말투·게시 대상 검토 완료',key='approve_'+d['id']+'_'+str(d['revision']))
            def approve():
                ok = run_action(lambda:(service.approve_draft(work['id'],d['id'],checked=checked,expected_revision=d['revision']),True)[1])
                if ok:
                    current = service.workspace(work['id'])
                    ordered = current['drafts']
                    at = next(i for i,item in enumerate(ordered) if item['id']==d['id'])
                    following = ordered[at+1:]+ordered[:at]
                    pending = next((item for item in following if not is_approved(item) and not item.get('stale_source')),None)
                    if pending:
                        st.session_state['review_filter_'+work['id']] = '검토 대기'
                        select_draft(pending['id'])
                        move_to(work,'review')
                    else:
                        move_to(work,'approval')
            save,approve_col = st.columns(2)
            save.button('수정 저장',disabled=not dirty or bool(service.busy()),on_click=save_edit,width='stretch')
            approve_col.button('승인·다음',type='primary',disabled=dirty or not checked or bool(service.busy()) or d.get('failed',False) or d.get('stale_source',False) or is_approved(d),on_click=approve,width='stretch')
            if is_approved(d):
                st.success('승인됨 · 미게시')
        with st.expander('미리보기'):
            paper(title,content)
    with right:
        st.markdown(f'<div class="studio-draft-meta">{esc(names.get(d["tone"],d["tone"]))} · {esc(d["model"])} · v{d["revision"]}</div>',unsafe_allow_html=True)
        st.subheader('원본')
        st.write(d.get('source_topic',''))
        with st.expander('페르소나'):
            st.write(names.get(d['tone'],d['tone']))
            st.write(pm.load_json('persona_profiles.json').get(d['tone'],{}).get('vocab_style',''))
        for warning in d.get('warnings',[]):
            st.warning(warning)
        if d.get('stale_source'):
            st.error('자료 변경 전 원고입니다. 새 자료로 다시 생성하세요.')
        with st.expander('생성 원문 / 제외된 댓글'):
            st.json(d.get('raw',{}))


def approval_page(service, work):
    try:
        packet = service.export_approved(work['id'])
    except ValueError:
        empty('승인 원고 없음')
        step_button(work,resume_step(work),'원고 검토' if work['drafts'] else '원고 준비')
        return
    st.subheader(f"승인한 원고 {len(packet['drafts'])}개")
    st.info('승인됨 · 미게시')
    for d in packet['drafts']:
        paper(d['title'],d['content'],f"{work['gallery']} · v{d['revision']} · 승인됨")
    markdown = '\n\n---\n\n'.join(f"# {d['title']}\n\n{d['content']}" for d in packet['drafts'])
    a,b = st.columns(2)
    a.download_button('승인 원고 Markdown 저장',markdown,file_name='approved-drafts.md',mime='text/markdown')
    b.download_button('승인 패키지 JSON 저장',json.dumps(packet,ensure_ascii=False,indent=2),file_name='approved-drafts.json',mime='application/json')
    from ghost_protocol.config import get_write_url
    st.link_button('게시판 글쓰기 직접 열기',get_write_url(work['gallery_type'],work['gallery']))


def workbench(service):
    work = choose_work(service)
    if not work:
        return
    st.markdown(f'<div class="studio-context"><span>게시판 <strong>{esc(work["gallery"])}</strong></span><span>모델 <strong>{esc(service.settings()["model"])}</strong></span><span>비용 <strong>{money(service.calls(work["id"]))}</strong></span></div>',unsafe_allow_html=True)
    stage_keys = list(STAGES)
    label_map = {key:f'{i+1} {value}' for i,(key,value) in enumerate(STAGES.items())}
    key = 'step_'+work['id']
    seen_key = 'stage_seen_'+work['id']
    last_key = 'last_step_'+work['id']
    ready = resume_step(work)
    state = (work['stage'],ready)
    if st.session_state.get(seen_key) != state:
        st.session_state[key] = ready
        st.session_state[seen_key] = state
    elif not st.session_state.get(key):
        st.session_state[key] = st.session_state.get(last_key,ready)
    if 'next_step_'+work['id'] in st.session_state:
        st.session_state[key] = st.session_state.pop('next_step_'+work['id'])
    step = st.radio('작업 단계',stage_keys,index=None,format_func=label_map.get,horizontal=True,key=key,label_visibility='collapsed')
    st.session_state[last_key] = step
    {'source':source_page,'analysis':analysis_page,'draft':draft_controls,'review':review_page,'approval':approval_page}[step](service,work)


def personas(service):
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
            if st.form_submit_button('추가 규칙 저장',type='primary',disabled=bool(service.busy())):
                settings['persona_notes'][tone] = notes
                if run_action(lambda:(service.save_settings({'rules':common,'persona_notes':settings['persona_notes']}),True)[1]):
                    st.success('추가 규칙을 저장했습니다.')
    with st.expander('작문 프롬프트'):
        st.code(pm.load('generate_post.txt'),language=None)
    with st.expander('규칙 저장 이력'):
        revisions = service.store.list('settings_revision')
        st.write(f'보존된 설정 버전 {len(revisions)}개')
        for r in revisions[:10]:
            st.caption(r.get('saved',''))
            st.json({'rules':r['rules'],'persona_notes':r['persona_notes']},expanded=False)


def lab(service):
    pairs = service.benchmark_pairs()
    if pairs:
        st.caption('합성 소재 · 2026.09.06 · 10쌍 · 계산액 $0.04008768 · 87.01초')
        idx = st.selectbox('비교할 소재',range(len(pairs)),format_func=lambda i:f"{i+1:02d} · {pairs[i]['rows'][0]['persona_name']}")
        pair = pairs[idx]
        st.write(pair['rows'][0]['source'])
        cols = st.columns(2,gap='large')
        for col,row in zip(cols,pair['rows']):
            with col:
                paper(row['draft']['title'],row['draft']['content'],row['model'])
                st.caption(f"{row['api_seconds']}초 · ${row['cost_usd']}")
        with st.expander('검증 결과'):
            st.warning('사실 오류·임의 댓글·페르소나 미준수 · 미승인 원고')
        def import_work():
            work = run_action(service.import_benchmark)
            if work:
                st.session_state['studio_work'] = work['id']
                st.session_state['studio_next_work'] = work['id']
                st.query_params.update({'view':'작업실','work':work['id']})
                st.session_state['studio_view'] = '작업실'
        st.button('기존 원고 20개를 작업실로 가져오기',disabled=bool(service.busy()),on_click=import_work)
    with st.expander('현재 작업으로 새 비교 실행'):
        works = service.workspaces()
        if not works:
            st.info('작업 없음')
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
    calls = service.calls()
    a,b,c = st.columns(3)
    a.metric('저장된 작업',len(service.workspaces()))
    b.metric('API 응답 기록',len(calls))
    c.metric('계산 비용',money(calls))
    st.caption('일반 유료 단가 기준 · 2026.09.06 · 과거 실험 비용 제외')
    jobs = service.jobs()
    if not jobs:
        empty('실행 기록 없음')
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
    st.link_button('기존 운영 콘솔 열기','?legacy=1',help='자동 게시·리허설 · 새 작업실과 동시 실행 금지')


def settings_page(service):
    settings = service.settings()
    configured = bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))
    if configured:
        st.success('API 키 설정됨 · 연결 미검증')
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
                st.success('설정 저장됨')


def render_studio():
    st.set_page_config(page_title='Ghost Protocol · Studio',page_icon='◌',layout='wide',initial_sidebar_state='collapsed')
    st.markdown('<style>'+Path(__file__).with_name('studio.css').read_text(encoding='utf-8')+'</style>',unsafe_allow_html=True)
    service = get_service(os.getenv('STUDIO_DATA_DIR',str(ROOT/'data/studio')))
    st.markdown('<header class="studio-mast"><div class="studio-brand">Ghost Protocol</div></header>',unsafe_allow_html=True)
    initial = st.query_params.get('view','작업실')
    if 'studio_next_view' in st.session_state:
        st.session_state['studio_view'] = st.session_state.pop('studio_next_view')
    if 'studio_view' not in st.session_state:
        st.session_state['studio_view'] = initial if initial in NAV else '작업실'
    view = st.radio('공간',NAV,index=None,horizontal=True,label_visibility='collapsed',key='studio_view')
    st.query_params['view'] = view
    if notice := st.session_state.pop('studio_notice',None):
        st.toast(notice)
    if error := st.session_state.pop('studio_error',None):
        st.error(error)
    progress(service)
    if view=='작업실':
        workbench(service)
    else:
        {'페르소나·규칙':personas,'실험실':lab,'운영 기록':history,'설정':settings_page}[view](service)
