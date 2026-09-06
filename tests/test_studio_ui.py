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
    next(b for b in app.button if b.label=='이 버전 승인').click().run()
    assert not app.exception
    assert next(r for r in app.radio if r.label=='작업 단계').value=='approval'
    assert any(i.value=='승인됨 · 미게시' for i in app.info)


def import_fixture(app):
    app.radio(key='studio_view').set_value('실험실').run()
    next(b for b in app.button if b.label=='기존 원고 20개를 작업실로 가져오기').click().run()
    return app


def test_unsaved_edit_survives_navigation_and_blocks_approval(app):
    import_fixture(app)
    next(t for t in app.text_input if t.label=='제목 수정').set_value('저장 전 제목').run()
    next(c for c in app.checkbox if c.label=='사실·말투·게시 대상 검토 완료').check().run()
    assert next(b for b in app.button if b.label=='이 버전 승인').disabled
    app.radio(key='studio_view').set_value('설정').run()
    app.radio(key='studio_view').set_value('작업실').run()
    assert not app.exception
    assert next(t for t in app.text_input if t.label=='제목 수정').value == '저장 전 제목'


def test_create_second_workspace_selects_new_work(app):
    import_fixture(app)
    next(t for t in app.text_input if t.label=='작업 이름').set_value('두 번째 작업')
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
    assert next(n for n in app.number_input if n.label=='만들 원고 수').value==1


def test_source_save_advances_and_keeps_work_after_reload(app):
    next(t for t in app.text_input if t.label=='작업 이름').set_value('자료 테스트')
    next(b for b in app.button if b.label=='작업 만들기').click().run()
    next(t for t in app.text_area if t.label=='원본 자료').set_value('달 그림자 관측')
    next(b for b in app.button if b.label=='자료 저장').click().run()
    assert not app.exception
    assert next(r for r in app.radio if r.label=='작업 단계').value=='analysis'


def test_panels_have_no_static_explanations(app):
    import_fixture(app)
    assert not app.caption
    assert not app.title
    assert any(b.label=='수정 저장' for b in app.button)
    assert next(b for b in app.button if b.label=='이 버전 승인').disabled
    app.radio(key='studio_view').set_value('설정').run()
    assert not app.caption
    assert not app.title
    assert len(app.number_input)==3
    assert any(b.label=='설정 저장' for b in app.button)
    assert not any('안전 규칙' in s.value for s in app.subheader)


def test_compact_generation_keeps_explicit_paid_consent(app):
    import_fixture(app)
    next(r for r in app.radio if r.label=='작업 단계').set_value('draft').run()
    consent = next(c for c in app.checkbox if c.label=='Google API 전송·과금 동의')
    assert consent.value is False
    next(b for b in app.button if b.label=='원고 생성').click().run()
    assert not app.exception
    assert any('API 사용량 동의' in e.value for e in app.error)
