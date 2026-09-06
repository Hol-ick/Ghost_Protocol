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
    assert any(b.label=='수집 시작' for b in app.button)


def test_minimum_batch_setting_does_not_break_generation_screen(app):
    import_fixture(app)
    app.radio(key='studio_view').set_value('설정').run()
    next(n for n in app.number_input if n.label=='한 번에 만들 원고 상한').set_value(1)
    next(b for b in app.button if b.label=='설정 저장').click().run()
    app.radio(key='studio_view').set_value('작업실').run()
    assert not app.exception
    assert not any(t.label=='소재' for t in app.text_area)


def test_source_page_has_no_direct_input_or_stored_database_path(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    assert not app.exception
    assert any(b.label=='수집 시작' for b in app.button)
    assert not any(t.label in ('원본 자료','작업 이름','소재') for t in list(app.text_area) + list(app.text_input))
    assert not any('DB 자료' in b.label for b in app.button)


def test_workbench_has_one_active_flow_and_no_stage_picker(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    assert not any(r.label=='작업 단계' for r in app.radio)
    assert any(b.label=='수집 시작' for b in app.button)


def test_collection_and_api_consent_checkboxes_are_absent(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    labels = [box.label for box in app.checkbox]
    assert '게시판 수집 동의' not in labels
    assert 'Google API 전송·과금 동의' not in labels


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


def test_historical_fixture_stays_in_review_without_source_controls(app):
    import_fixture(app)
    assert any(s.label=='검토할 원고' for s in app.selectbox)
    assert not any(b.label=='자료 분석' for b in app.button)


def test_last_approval_exports_and_edit_returns_to_review(app):
    import_fixture(app)
    for _ in range(20):
        next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
        next(b for b in app.button if b.label=='승인·다음').click().run()
        assert not app.exception
    assert any(s.value=='승인한 원고 20개' for s in app.subheader)
    next(r for r in app.radio if r.label=='원고 필터').set_value('승인됨').run()
    next(t for t in app.text_input if t.label=='제목 수정').set_value('승인 후 수정').run()
    next(b for b in app.button if b.label=='수정 저장').click().run()
    assert next(t for t in app.text_input if t.label=='제목 수정').value=='승인 후 수정'
    refreshed = AppTest.from_file('app.py').run()
    assert not refreshed.exception
    assert any(s.label=='검토할 원고' for s in refreshed.selectbox)


def test_approval_does_not_resume_to_export_while_pending_drafts_remain(app):
    import_fixture(app)
    first_id = next(s for s in app.selectbox if s.label=='검토할 원고').value
    next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
    next(b for b in app.button if b.label=='승인·다음').click().run()
    refreshed = AppTest.from_file('app.py').run()
    assert not refreshed.exception
    assert next(s for s in refreshed.selectbox if s.label=='검토할 원고').value != first_id


def test_lab_missing_source_link_opens_the_correct_work(app):
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    app.radio(key='studio_view').set_value('실험실').run()
    assert not app.exception
    assert app.radio(key='studio_view').value=='실험실'
