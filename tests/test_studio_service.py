import pytest

from ghost_protocol.studio.service import StudioService
from ghost_protocol.studio.policy import cost


class FakeBackend:
    def collect(self, work, payload, log):
        return {
            'source_kind': 'board_collection',
            'gallery_id': work['gallery'],
            'titles': ['달의 명암 경계가 보인다'],
            'comments': ['경계가 선명하네'],
            'raw_posts': [{'title':'달의 명암 경계가 보인다', 'content':'망원경으로 달 가장자리를 봄', 'comments':['경계가 선명하네']}],
            'source_access': {'status': 'ok'},
        }

    def analyze(self, work, model, meter):
        return {'summary': '달의 명암 관찰', 'hot_topics': ['달 그림자']}

    def generate(self, work, model, tone, topic, rules, meter):
        return {'title': '달의 그림자', 'content': '경계가 보임', 'target_comments': [{'post_no':'1','comment':'가짜'}]}


def test_workspace_survives_restart(tmp_path):
    studio = StudioService(tmp_path)
    work = studio.create_workspace('첫 원고', 'universe', 'board')
    restored = StudioService(tmp_path).workspace(work['id'])
    assert restored['name'] == '첫 원고'
    assert restored['stage'] == 'source'
    assert restored['drafts'] == []


def test_blocked_source_cannot_start_analysis(tmp_path):
    class BlockedBackend(FakeBackend):
        def collect(self, work, payload, log):
            return {'source_kind':'board_collection','titles': [], 'comments': [],
                    'source_access': {'status':'blocked','reason':'empty_body'}}
    studio = StudioService(tmp_path, BlockedBackend())
    work = studio.create_workspace('차단', 'universe')
    job = studio.start(work['id'], 'collect', {})
    studio.wait(job)
    assert studio.job(job)['status'] == 'failed'
    with pytest.raises(ValueError, match='게시판 수집'):
        studio.start(work['id'], 'analyze', {})


def test_edit_revokes_approval_and_exports_no_invented_comments(tmp_path):
    studio = StudioService(tmp_path, FakeBackend())
    work = studio.create_workspace('검토', 'universe')
    studio.wait(studio.start(work['id'], 'collect', {}))
    studio.wait(studio.start(work['id'], 'analyze', {}))
    studio.confirm_analysis(work['id'])
    studio.wait(studio.start(work['id'], 'generate', {'tones':['neutral'], 'count':1}))
    draft = studio.workspace(work['id'])['drafts'][0]
    assert draft['target_comments'] == []
    assert draft['warnings']
    with pytest.raises(ValueError):
        studio.export_approved(work['id'])
    studio.approve_draft(work['id'], draft['id'], checked=True, expected_revision=1)
    assert len(studio.export_approved(work['id'])['drafts']) == 1
    studio.save_draft(work['id'], draft['id'], '수정 제목', '수정 본문', expected_revision=1)
    with pytest.raises(ValueError):
        studio.export_approved(work['id'])
    with pytest.raises(ValueError, match='다른'):
        studio.save_draft(work['id'], draft['id'], '오래된', '편집', expected_revision=1)


def test_cost_accounts_for_cache_and_thinking():
    assert cost('gemini-2.5-flash', {'prompt_token_count':10000,'cached_content_token_count':2000,
        'candidates_token_count':100,'thoughts_token_count':50}) == '0.002835'


def prepared(tmp_path, backend=None):
    studio = StudioService(tmp_path, backend or FakeBackend())
    work = studio.create_workspace('안전 검증', 'universe')
    studio.wait(studio.start(work['id'], 'collect', {}))
    studio.wait(studio.start(work['id'], 'analyze', {}))
    studio.confirm_analysis(work['id'])
    return studio, work['id']


def test_generation_requires_analysis_confirmation(tmp_path):
    studio = StudioService(tmp_path, FakeBackend())
    work = studio.create_workspace('미확인', 'universe')
    studio.wait(studio.start(work['id'], 'collect', {}))
    studio.wait(studio.start(work['id'], 'analyze', {}))
    with pytest.raises(ValueError, match='먼저 확인'):
        studio.start(work['id'], 'generate', {'tones':['neutral']})


def test_model_cannot_confirm_its_own_analysis(tmp_path):
    class SelfConfirmedBackend(FakeBackend):
        def analyze(self, *args):
            return {'summary':'분석 결과', 'confirmed':True}
    studio = StudioService(tmp_path,SelfConfirmedBackend())
    wid = studio.create_workspace('확인 주체', 'universe')['id']
    studio.wait(studio.start(wid,'collect',{}))
    studio.wait(studio.start(wid,'analyze',{}))
    assert studio.workspace(wid)['analysis']['confirmed'] is False


def test_source_change_invalidates_analysis_and_approved_drafts(tmp_path):
    studio, wid = prepared(tmp_path)
    studio.wait(studio.start(wid, 'generate', {'tones':['neutral']}))
    d = studio.workspace(wid)['drafts'][0]
    studio.approve_draft(wid, d['id'], checked=True, expected_revision=1)
    studio.wait(studio.start(wid, 'collect', {}))
    assert studio.workspace(wid)['analysis'] == {}
    assert studio.workspace(wid)['drafts'][0]['stale_source']
    assert len(studio.store.list('source_revision')) == 1
    with pytest.raises(ValueError):
        studio.export_approved(wid)
    with pytest.raises(ValueError):
        studio.approve_draft(wid, d['id'], checked=True, expected_revision=1)


def test_approval_rejects_stale_version_from_another_tab(tmp_path):
    studio, wid = prepared(tmp_path)
    studio.wait(studio.start(wid, 'generate', {'tones':['neutral']}))
    d = studio.workspace(wid)['drafts'][0]
    studio.save_draft(wid, d['id'], '새 제목', '새 본문', expected_revision=1)
    with pytest.raises(ValueError, match='최신 원고'):
        studio.approve_draft(wid, d['id'], checked=True, expected_revision=1)


def test_cancel_preserves_partial_result_and_blocks_duplicate_jobs(tmp_path):
    import threading
    entered, release = threading.Event(), threading.Event()
    class WaitingBackend(FakeBackend):
        def generate(self, *args):
            entered.set()
            assert release.wait(5)
            return super().generate(*args)
    studio, wid = prepared(tmp_path, WaitingBackend())
    job = studio.start(wid, 'generate', {'tones':['neutral'],'count':3})
    try:
        assert entered.wait(3)
        with pytest.raises(ValueError, match='진행 중'):
            studio.start(wid, 'generate', {'tones':['neutral']})
        with pytest.raises(ValueError):
            studio.start(wid, 'collect', {})
        studio.cancel(job)
    finally:
        release.set()
    studio.wait(job)
    assert studio.job(job)['status'] == 'cancelled'
    assert studio.job(job)['progress'] == 1
    assert len(studio.workspace(wid)['drafts']) == 1


def test_restart_marks_unfinished_job_interrupted_without_retry(tmp_path):
    studio = StudioService(tmp_path, FakeBackend())
    studio.store.put('job','stopped', {'id':'stopped','status':'running','progress':1,'total':3})
    restored = StudioService(tmp_path, FakeBackend())
    assert restored.job('stopped')['status'] == 'interrupted'
    assert not restored.busy()


def test_parse_failure_stops_batch_and_retains_raw_response(tmp_path):
    class BrokenBackend(FakeBackend):
        def generate(self, *args):
            return {'title':'','content':'','_parse_error':True,'_raw_response':'not-json'}
    studio, wid = prepared(tmp_path, BrokenBackend())
    job = studio.start(wid, 'generate', {'tones':['neutral'],'count':10})
    studio.wait(job)
    assert studio.job(job)['status'] == 'failed'
    drafts = studio.workspace(wid)['drafts']
    assert len(drafts) == 1 and drafts[0]['raw']['_raw_response'] == 'not-json'
    with pytest.raises(ValueError):
        studio.approve_draft(wid, drafts[0]['id'], checked=True, expected_revision=1)


def test_comparison_has_identical_inputs_and_selected_persona(tmp_path):
    received = []
    class CaptureBackend(FakeBackend):
        def generate(self, work, model, tone, topic, rules, meter):
            received.append((model,tone,topic,rules))
            return super().generate(work,model,tone,topic,rules,meter)
    studio, wid = prepared(tmp_path, CaptureBackend())
    studio.save_settings({'rules':'공통 규칙', 'persona_notes':{'neutral':'차분히'}})
    studio.wait(studio.start(wid,'compare',{'tones':['neutral'],'count':1}))
    assert len(received) == 2
    assert received[0][0] != received[1][0]
    assert received[0][1:] == received[1][1:]
    assert received[0][1] == 'neutral' and received[0][3] == '공통 규칙\n차분히'
    assert '[게시판 여론 패킷]' in received[0][2]


def test_import_is_idempotent_and_settings_survive_restart(tmp_path):
    studio = StudioService(tmp_path)
    work = studio.import_benchmark()
    assert len(work['drafts']) == 20
    assert studio.import_benchmark()['id'] == work['id']
    assert len(studio.workspaces()) == 1
    studio.save_settings({'model':'gemini-3.1-flash-lite','max_drafts':1,'rules':'보존 규칙'})
    restored = StudioService(tmp_path)
    assert restored.settings()['max_drafts'] == 1
    assert restored.settings()['rules'] == '보존 규칙'
    assert len(restored.store.list('settings_revision')) == 1


def test_offline_mode_blocks_collect_and_paid_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIO_OFFLINE','1')
    studio = StudioService(tmp_path)
    wid = studio.create_workspace('오프라인', 'universe')['id']
    job = studio.start(wid,'collect',{})
    studio.wait(job)
    assert studio.job(job)['status'] == 'failed'
    assert '오프라인' in studio.job(job)['error']
    with pytest.raises(ValueError, match='게시판 수집'):
        studio.start(wid,'analyze',{})
    assert studio.calls() == []


def test_generation_uses_collected_board_opinion_packet(tmp_path):
    captured = []
    class CaptureBackend(FakeBackend):
        def generate(self, work, model, tone, topic, rules, meter):
            captured.append(topic)
            return super().generate(work, model, tone, topic, rules, meter)
    studio, wid = prepared(tmp_path, CaptureBackend())
    studio.wait(studio.start(wid, 'generate', {'tones':['neutral'], 'count':1}))
    assert '[게시판 여론 패킷]' in captured[0]
    assert '원본 글: 달의 명암 경계가 보인다' in captured[0]
    assert '원본 댓글: 경계가 선명하네' in captured[0]
    assert '달의 명암 관찰' in captured[0]
