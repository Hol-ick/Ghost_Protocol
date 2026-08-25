from ghost_protocol import prompt_manager as pm
from ghost_protocol.application.prompt_compiler import compile_post_prompt


def test_compiler_keeps_persona_and_source_rules_but_removes_runtime_meta() -> None:
    master = """[입력]
- 이번 역할: 장면 하나 붙이는 사람

[작업]
구체 장면 하나에 반응한다.

[참여자 관점]
외부 평가자가 아니라 이미 대화 중인 사람처럼 쓴다.

[반복 방지]
앱 검증기가 중복을 검사한다.

[출력 전 점검]
모델이 모든 품질 검사를 수행한다.

[댓글]
댓글을 길게 만든다.

[JSON 필드]
- title
- content
"""

    compiled = compile_post_prompt(master, include_comments=False)

    assert "장면 하나 붙이는 사람" in compiled
    assert "이미 대화 중인 사람" in compiled
    assert "[반복 방지]" not in compiled
    assert "[출력 전 점검]" not in compiled
    assert "[댓글]" not in compiled
    assert "title" in compiled and "content" in compiled
    assert "JSON 객체 하나만 출력" in compiled


def test_full_compiler_preserves_master_quality_rules() -> None:
    master = """[입력]
브리핑

[반복 방지]
같은 생성 골격을 반복하지 않는다.

[출력 전 점검]
입력에 없는 변화를 만들지 않는다.

[댓글]
타겟 글에만 댓글을 단다.
"""

    compiled = compile_post_prompt(master, include_comments=False, mode="full")

    assert "[반복 방지]" in compiled
    assert "같은 생성 골격을 반복하지 않는다." in compiled
    assert "[출력 전 점검]" in compiled
    assert "[댓글]" not in compiled
    assert "입력에 없는 수치·변화·비교" in compiled


def test_compiler_keeps_comment_rules_when_targets_exist() -> None:
    master = """[입력]
소재

[댓글]
타겟 글과 같은 구체 소재에 짧게 반응한다.

[JSON 필드]
title/content
"""

    compiled = compile_post_prompt(master, include_comments=True)

    assert "[댓글]" in compiled
    assert "타겟 글과 같은 구체 소재" in compiled


def test_compiler_does_not_inject_game_specific_contract_into_other_domains() -> None:
    master = "[입력]\n" + pm.render("shared_writing_contract.txt") + "\n\n[작업]\n구체 소재에 반응한다."

    compiled = compile_post_prompt(master, include_comments=False)

    assert "게임명·카드·룰·턴수" not in compiled
    assert "구체 명사·수치·사진·장면" in compiled
