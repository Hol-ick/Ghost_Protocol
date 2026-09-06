import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('STUDIO_DATA_DIR',str(tmp_path))
    monkeypatch.setenv('STUDIO_OFFLINE','1')
    return AppTest.from_file('app.py',default_timeout=15).run()


def test_empty_state_and_navigation(app):
    assert not app.exception
    assert not app.title
    assert any(b.label=='작업 만들기' for b in app.button)
    for view in ('페르소나·규칙','실험실','운영 기록','설정','작업실'):
        app.radio(key='studio_view').set_value(view).run()
        assert not app.exception


def test_import_benchmark_edit_and_approve(app):
    app.radio(key='studio_view').set_value('실험실').run()
    next(b for b in app.button if b.label=='기존 원고 20개를 작업실로 가져오기').click().run()
    assert not app.exception
    assert any('원고 필터' == r.label for r in app.radio)
    next(t for t in app.text_input if t.label=='제목 수정').set_value('검증용 수정 제목').run()
    next(b for b in app.button if b.label=='수정 저장').click().run()
    assert not app.exception
    assert next(t for t in app.text_input if t.label=='제목 수정').value=='검증용 수정 제목'
    next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
    first_id = next(s for s in app.selectbox if s.label=='검토할 원고').value
    next(b for b in app.button if b.label=='승인·다음').click().run()
    assert not app.exception
    assert next(r for r in app.radio if r.label=='작업 단계').value=='review'
    assert next(s for s in app.selectbox if s.label=='검토할 원고').value != first_id
    assert not next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').value


def import_fixture(app):
    app.radio(key='studio_view').set_value('실험실').run()
    next(b for b in app.button if b.label=='기존 원고 20개를 작업실로 가져오기').click().run()
    return app


def test_unsaved_edit_survives_navigation_and_blocks_approval(app):
    import_fixture(app)
    next(t for t in app.text_input if t.label=='제목 수정').set_value('저장 전 제목').run()
    next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
    assert next(b for b in app.button if b.label=='승인·다음').disabled
    app.radio(key='studio_view').set_value('설정').run()
    app.radio(key='studio_view').set_value('작업실').run()
    assert not app.exception
    assert next(t for t in app.text_input if t.label=='제목 수정').value == '저장 전 제목'


def test_create_second_workspace_selects_new_work(app):
    import_fixture(app)
    next(b for b in app.button if b.label=='새 작업').click().run()
    next(t for t in app.text_input if t.label=='게시판 ID').set_value('space')
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    assert not app.exception
    assert next(r for r in app.radio if r.label=='작업 단계').value=='source'


def test_minimum_batch_setting_does_not_break_generation_screen(app):
    import_fixture(app)
    app.radio(key='studio_view').set_value('설정').run()
    next(n for n in app.number_input if n.label=='한 번에 만들 원고 상한').set_value(1)
    next(b for b in app.button if b.label=='설정 저장').click().run()
    app.radio(key='studio_view').set_value('작업실').run()
    next(r for r in app.radio if r.label=='작업 단계').set_value('draft').run()
    assert not app.exception
    assert not any(t.label=='소재' for t in app.text_area)


def test_source_page_has_no_direct_input_or_stored_database_path(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    assert not app.exception
    assert any(b.label=='수집 시작' for b in app.button)
    assert not any(t.label in ('원본 자료','작업 이름','소재') for t in list(app.text_area) + list(app.text_input))
    assert not any('DB 자료' in b.label for b in app.button)


def test_panels_have_no_static_explanations(app):
    import_fixture(app)
    assert not app.caption
    assert not app.title
    assert any(b.label=='수정 저장' for b in app.button)
    assert next(b for b in app.button if b.label=='승인·다음').disabled
    app.radio(key='studio_view').set_value('설정').run()
    assert not app.caption
    assert not app.title
    assert len(app.number_input)==3
    assert any(b.label=='설정 저장' for b in app.button)
    assert not any('안전 규칙' in s.value for s in app.subheader)


def test_source_page_requires_consent_before_collection(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    collect = next(b for b in app.button if b.label=='수집 시작')
    assert collect.disabled
    next(c for c in app.checkbox if c.label=='게시판 수집 동의').check().run()
    assert not next(b for b in app.button if b.label=='수집 시작').disabled


def test_review_next_previous_preserves_unsaved_edit(app):
    import_fixture(app)
    first_id = next(s for s in app.selectbox if s.label=='검토할 원고').value
    next(t for t in app.text_input if t.label=='제목 수정').set_value('이동해도 남는 제목').run()
    next(b for b in app.button if b.label=='다음').click().run()
    assert next(s for s in app.selectbox if s.label=='검토할 원고').value != first_id
    next(b for b in app.button if b.label=='이전').click().run()
    assert next(t for t in app.text_input if t.label=='제목 수정').value=='이동해도 남는 제목'
    assert next(b for b in app.button if b.label=='승인·다음').disabled


def test_modal_cancel_keeps_current_work(app):
    import_fixture(app)
    wid = app.query_params['work'][0]
    next(b for b in app.button if b.label=='새 작업').click().run()
    next(b for b in app.button if b.label=='취소').click().run()
    assert not app.exception
    assert app.query_params['work'][0] == wid
    assert not any(t.label=='게시판 ID' for t in app.text_input)


def test_analysis_fixture_cannot_bypass_board_collection(app):
    import_fixture(app)
    next(r for r in app.radio if r.label=='작업 단계').set_value('analysis').run()
    assert any('수집 필요' in info.value for info in app.info)
    assert not any(t.label=='이번 작문 지시' for t in app.text_area)


def test_last_approval_exports_and_edit_returns_to_review(app):
    import_fixture(app)
    for _ in range(20):
        next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
        next(b for b in app.button if b.label=='승인·다음').click().run()
        assert not app.exception
    assert next(r for r in app.radio if r.label=='작업 단계').value=='approval'
    assert any(s.value=='승인한 원고 20개' for s in app.subheader)
    next(r for r in app.radio if r.label=='작업 단계').set_value('review').run()
    next(r for r in app.radio if r.label=='원고 필터').set_value('승인됨').run()
    next(t for t in app.text_input if t.label=='제목 수정').set_value('승인 후 수정').run()
    next(b for b in app.button if b.label=='수정 저장').click().run()
    assert next(r for r in app.radio if r.label=='작업 단계').value=='review'
    assert next(t for t in app.text_input if t.label=='제목 수정').value=='승인 후 수정'
    refreshed = AppTest.from_file('app.py').run()
    assert not refreshed.exception
    assert next(r for r in refreshed.radio if r.label=='작업 단계').value=='review'


def test_approval_does_not_resume_to_export_while_pending_drafts_remain(app):
    import_fixture(app)
    first_id = next(s for s in app.selectbox if s.label=='검토할 원고').value
    next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
    next(b for b in app.button if b.label=='승인·다음').click().run()
    refreshed = AppTest.from_file('app.py').run()
    assert not refreshed.exception
    assert next(r for r in refreshed.radio if r.label=='작업 단계').value=='review'
    assert next(s for s in refreshed.selectbox if s.label=='검토할 원고').value != first_id


def test_lab_missing_source_link_opens_the_correct_work(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    app.radio(key='studio_view').set_value('실험실').run()
    next(b for b in app.button if b.label=='자료·분석 확인').click().run()
    assert not app.exception
    assert app.radio(key='studio_view').value=='작업실'
    assert next(r for r in app.radio if r.label=='작업 단계').value=='source'
