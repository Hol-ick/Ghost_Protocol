"""Full Studio interactions with isolated storage and metered test responses."""
from types import SimpleNamespace
import threading
import pytest
from streamlit.testing.v1 import AppTest
from ghost_protocol.studio import ui
from ghost_protocol.studio.service import StudioService


class WorkflowBackend:
    def collect(self, work, payload, log):
        log('목록 응답 HTTP 200')
        return {'source_kind':'board_collection', 'source_access':{'status':'ok'},
                'titles':['달 그림자'], 'comments':['경계가 보임']}

    def analyze(self, work, model, meter):
        meter(model, {'purpose':'analysis'}, SimpleNamespace(text='분석 응답',
              usage={'prompt_token_count':1000, 'candidates_token_count':100}), .1)
        return {'summary':'달의 명암 관찰', 'hot_topics':['달 그림자']}

    def generate(self, work, model, tone, topic, rules, meter):
        meter(model, {'purpose':'generation'}, SimpleNamespace(text='원고 응답',
              usage={'prompt_token_count':1000, 'candidates_token_count':100}), .1)
        return {'title':'달 그림자가 선명하네', 'content':'경계선이 잘 보임'}


def test_same_name_work_selection_survives_updates_and_full_workflow(tmp_path, monkeypatch):
    service = StudioService(tmp_path, WorkflowBackend())
    works = [service.create_workspace('universe','universe') for _ in range(3)]
    monkeypatch.setattr(ui, 'get_service', lambda *args: service)
    app = AppTest.from_file('app.py').run()
    selected = works[0]['id']
    app.selectbox(key='studio_work_selector').set_value(selected).run()
    assert app.query_params['work'] == [selected]
    next(b for b in app.button if b.label=='수집 시작').click().run()
    service.wait(service.jobs()[0]['id'])
    app.run()
    assert app.query_params['work'] == [selected]
    next(b for b in app.button if b.label=='자료 분석').click().run()
    service.wait(service.jobs()[0]['id'])
    app.run()
    next(b for b in app.button if b.label=='분석 확인 · 원고 제작으로').click().run()
    assert app.query_params['work'] == [selected]
    next(n for n in app.number_input if n.label=='만들 원고 수').set_value(1)
    next(b for b in app.button if b.label=='원고 생성').click().run()
    service.wait(service.jobs()[0]['id'])
    app.run()
    assert not app.exception
    assert app.query_params['work'] == [selected]
    assert any(s.label=='검토할 원고' for s in app.selectbox)
    assert len(service.workspace(selected)['drafts']) == 1
    cost_before = ui.money(service.calls(selected))
    assert cost_before != '$0.00000'
    for view in ('설정','운영 기록','페르소나·규칙','실험실','작업실'):
        app.radio(key='studio_view').set_value(view).run()
        assert not app.exception
        assert app.query_params['work'] == [selected]
    refreshed = AppTest.from_file('app.py')
    refreshed.query_params['work'] = selected
    refreshed.run()
    assert not refreshed.exception
    assert refreshed.query_params['work'] == [selected]
    assert any(s.label=='검토할 원고' for s in refreshed.selectbox)
    assert ui.money(service.calls(selected)) == cost_before
    refreshed.selectbox(key='studio_work_selector').set_value(None).run()
    assert not refreshed.exception
    assert refreshed.query_params['work']==[selected]


def test_analysis_controls_name_the_running_state_then_enable_confirmation(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class SlowAnalysisBackend(WorkflowBackend):
        def analyze(self, *args):
            entered.set()
            assert release.wait(5)
            return super().analyze(*args)

    service = StudioService(tmp_path, SlowAnalysisBackend())
    work = service.create_workspace('분석 진행 표시', 'universe')
    service.wait(service.start(work['id'], 'collect', {}))
    monkeypatch.setattr(ui, 'get_service', lambda *args: service)
    app = AppTest.from_file('app.py')
    app.query_params['work'] = work['id']
    app.run()
    next(button for button in app.button if button.label == '자료 분석').click().run()
    assert entered.wait(3)
    assert next(button for button in app.button if button.label == '분석 중…').disabled
    assert next(button for button in app.button if button.label == '분석 완료 대기').disabled
    release.set()
    service.wait(service.jobs()[0]['id'])
    app.run()
    assert not next(button for button in app.button if button.label == '분석 확인 · 원고 제작으로').disabled


def test_detailed_failure_and_operator_events_survive_restart(tmp_path,monkeypatch):
    class BrokenBackend(WorkflowBackend):
        def analyze(self,*args):
            raise RuntimeError('connection lost api_key=hidden-token')
    s = StudioService(tmp_path,BrokenBackend())
    w = s.create_workspace('오류 검증','universe')
    s.wait(s.start(w['id'],'collect',{}))
    jid = s.start(w['id'],'analyze',{})
    s.wait(jid)
    restored = StudioService(tmp_path,WorkflowBackend())
    job = restored.job(jid)
    assert job['status']=='failed'
    assert job['exception']['type']=='RuntimeError'
    assert job['exception']['frames'][-1]['function']=='analyze'
    assert 'hidden-token' not in str(job)
    assert 'connection lost' in ui.timeline_text(restored,w['id'])
    assert restored.events(w['id'])[0]['action']=='workspace_created'
    monkeypatch.setattr(ui,'get_service',lambda *args:restored)
    app=AppTest.from_file('app.py')
    app.query_params['work']=w['id']
    app.run()
    assert not app.exception
    assert any('connection lost' in e.value for e in app.error)
    next(b for b in app.button if b.label=='실행 오류 상세').click().run()
    assert any('RuntimeError' in c.value for c in app.code)
    with pytest.raises(ValueError,match='분석 실패'):
        restored.start(w['id'],'generate',{'tones':['neutral']})


def test_cancel_stops_remaining_drafts_and_rejects_duplicate_job(tmp_path):
    entered,release = threading.Event(),threading.Event()
    class SlowBackend(WorkflowBackend):
        def generate(self,*args):
            entered.set()
            assert release.wait(5)
            return super().generate(*args)
    s = StudioService(tmp_path,SlowBackend())
    w=s.create_workspace('중단','universe')
    s.wait(s.start(w['id'],'collect',{}))
    s.wait(s.start(w['id'],'analyze',{}))
    s.confirm_analysis(w['id'])
    jid=s.start(w['id'],'generate',{'tones':['neutral'],'count':3})
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError,match='진행 중'):
            s.start(w['id'],'generate',{'tones':['neutral']})
        s.cancel(jid)
    finally:
        release.set()
    s.wait(jid)
    assert s.job(jid)['status']=='cancelled'
    assert len(s.workspace(w['id'])['drafts'])==1
    assert any(e['action']=='cancel_requested' for e in s.events(w['id']))


def test_compare_edit_approve_export_and_settings_audit(tmp_path):
    s=StudioService(tmp_path,WorkflowBackend())
    w=s.create_workspace('비교','universe')
    s.wait(s.start(w['id'],'collect',{}))
    s.wait(s.start(w['id'],'analyze',{}))
    s.confirm_analysis(w['id'])
    jid=s.start(w['id'],'compare',{'tones':['neutral'],'count':1})
    s.wait(jid)
    ds=s.workspace(w['id'])['drafts']
    assert len(ds)==2 and ds[0]['model']!=ds[1]['model']
    d=ds[0]
    s.save_draft(w['id'],d['id'],'검토한 제목','본문',expected_revision=1)
    s.approve_draft(w['id'],d['id'],checked=True,expected_revision=2)
    assert s.export_approved(w['id'])['drafts'][0]['title']=='검토한 제목'
    with pytest.raises(ValueError,match='다른 편집'):
        s.save_draft(w['id'],d['id'],'오래된 제목','',expected_revision=1)
    s.save_settings({'rules':'공통 규칙','persona_notes':{'neutral':'추가 규칙'}})
    restored=StudioService(tmp_path,WorkflowBackend())
    assert restored.settings()['persona_notes']['neutral']=='추가 규칙'
    assert {'analysis_confirmed','draft_saved','draft_approved'} <= {e['action'] for e in restored.events(w['id'])}
    assert any(e['action']=='settings_saved' for e in restored.events())
    assert len(restored.calls(w['id']))==3
