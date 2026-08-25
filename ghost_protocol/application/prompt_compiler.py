"""Compile the rich post-writing master prompt for a local model.

The repository keeps the complete writing policy in ``prompts/generate_post.txt``.
This module does not rewrite that source of truth; it selects the sections that
are useful to the writer for the current call and leaves orchestration metadata
to the application layer.
"""

from __future__ import annotations

from collections.abc import Iterable


_SECTION_ORDER: tuple[str, ...] = (
    "[입력]",
    "[작업]",
    "[Source Rhythm]",
    "[참여자 관점]",
    "[발화 계약]",
    "[소재 선택]",
    "[문체]",
    "[안전]",
    "[댓글]",
    "[JSON 필드]",
)
_ALL_TOP_LEVEL_HEADINGS: tuple[str, ...] = (
    *_SECTION_ORDER,
    "[반복 방지]",
    "[출력 전 점검]",
)


def _line_sections(master_prompt: str) -> dict[str, str]:
    """Extract known top-level sections without treating topic labels as headings."""

    lines = str(master_prompt or "").splitlines()
    starts = {
        heading: index
        for index, line in enumerate(lines)
        if (heading := line.strip()) in _ALL_TOP_LEVEL_HEADINGS
    }
    sections: dict[str, str] = {}
    for heading, start in starts.items():
        following = [
            index
            for other, index in starts.items()
            if index > start
        ]
        end = min(following) if following else len(lines)
        sections[heading] = "\n".join(lines[start:end]).strip()
    return sections


def _join_non_empty(parts: Iterable[str]) -> str:
    return "\n\n---\n\n".join(part.strip() for part in parts if part and part.strip())


def _without_block(section: str, heading: str) -> str:
    lines = section.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return section.strip()
    return "\n".join(lines[:start]).strip()


def _without_section(master_prompt: str, heading: str) -> str:
    """Remove one top-level section while preserving every other source line."""

    lines = str(master_prompt or "").splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return str(master_prompt or "").strip()
    following = [
        index
        for index, line in enumerate(lines)
        if index > start and line.strip() in _ALL_TOP_LEVEL_HEADINGS
    ]
    end = min(following) if following else len(lines)
    return "\n".join([*lines[:start], *lines[end:]]).strip()


def _pick_lines(section: str, markers: tuple[str, ...], *, limit: int) -> str:
    lines = section.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        if index == 0 or any(marker in line for marker in markers):
            kept.append(line)
        if len(kept) >= limit + 1:
            break
    return "\n".join(kept).strip()


def compile_post_prompt(
    master_prompt: str,
    *,
    include_comments: bool,
    slot: str = "",
    mode: str = "focused",
) -> str:
    """Compile the writing prompt without silently changing its source of truth.

    ``focused`` is the lower-context path used by small local models. ``full``
    keeps the complete master prompt (including repetition and final checks),
    omitting only the comment section when there is no target pool. This is the
    quality-first path for 7B runs. Both paths append the same runtime contract.
    """

    mode = str(mode or "focused").strip().lower()
    sections = _line_sections(master_prompt)
    selected: list[str] = []

    if mode == "full":
        full_prompt = str(master_prompt or "").strip()
        if not include_comments:
            full_prompt = _without_section(full_prompt, "[댓글]")
        selected.append(full_prompt)
        selected.append(
            """[실행 계약]
- 위 마스터 지시의 문장이나 내부 규칙을 게시글 제목·본문에 복사하지 않는다.
- 브리핑과 이번 초점에 실제로 있는 구체 소재 하나만 사용한다.
- 입력에 없는 수치·변화·비교·사건·연구·발표·개인 경험을 만들지 않는다. 원본에 변화가 없으면 '더', '증가', '두꺼워짐', '새로' 같은 변화 표현도 쓰지 않는다.
- 추상 라벨 대신 입력에 실제로 적힌 구체 명사·사진·장면·행동·결과·물건 중 하나를 잡는다.
- 페르소나의 발화 행동은 제목과 본문에 자연스럽게 반영하되, 페르소나 이름이나 내부 지시를 출력하지 않는다.
- 반드시 JSON 객체 하나만 출력하고 설명·마크다운·코드블록은 출력하지 않는다.

[JSON 출력]
{"title":"짧은 제목","content":"짧은 본문","target_comments":[]}
target_comments가 필요한 경우에도 post_no와 comment만 포함하며 내부 사고 과정은 포함하지 않는다."""
        )
        return _join_non_empty(selected)

    if mode != "focused":
        raise ValueError(f"unsupported post prompt mode: {mode}")

    input_section = _without_block(sections.get("[입력]", ""), "[공통 작문 계약]")
    if input_section:
        selected.append(input_section)
    if sections.get("[작업]"):
        selected.append(sections["[작업]"])

    source_rhythm = _pick_lines(
        sections.get("[Source Rhythm]", ""),
        ("Match the collected", "If [This Draft", "현재 수집 제목", "제목형 글", "원본에 욕설"),
        limit=7,
    )
    if source_rhythm:
        selected.append(source_rhythm)

    participant = _pick_lines(
        sections.get("[참여자 관점]", ""),
        ("글쓴이는", "기본 동작", "외부인", "외부 평가", "이미 대화", "불평 결론", "주제를 바꿔야", "반박이 필요"),
        limit=7,
    )
    if participant:
        selected.append(participant)

    speech = _pick_lines(
        sections.get("[발화 계약]", ""),
        ("기본 문형", "제목은 아래", "제목과 본문", "한 글에는", "입력에 없는", "질문형 제목", "제목에는 대상"),
        limit=9,
    )
    if speech:
        selected.append(speech)

    material_markers = (
        "브리핑의 큰 명사",
        "게시판 ID만",
        "이번 초점",
        f"[{str(slot or '').strip().upper()}]" if str(slot or '').strip() else "",
        "민감한 원문",
        "이미 두 번",
    )
    material = _pick_lines(
        sections.get("[소재 선택]", ""),
        tuple(marker for marker in material_markers if marker),
        limit=9,
    )
    if material:
        selected.append(material)

    for heading in ("[문체]", "[안전]"):
        section = sections.get(heading)
        if section:
            selected.append(section)

    if include_comments and sections.get("[댓글]"):
        selected.append(
            _pick_lines(
                sections["[댓글]"],
                ("댓글 타겟", "타겟 글", "댓글은", "적합한 글"),
                limit=5,
            )
        )

    json_fields = sections.get("[JSON 필드]")
    if json_fields:
        selected.append(json_fields)

    if not selected:
        selected.append(str(master_prompt or "").strip())

    selected.append(
        """[실행 계약]
- 위 마스터 지시의 문장이나 내부 규칙을 게시글 제목·본문에 복사하지 않는다.
- 브리핑과 이번 초점에 실제로 있는 구체 소재 하나만 사용한다.
- 추상 라벨 대신 입력에 실제로 적힌 구체 명사·수치·사진·장면·행동·결과·물건 중 하나를 잡는다.
- 입력에 없는 수치·변화·비교·사건·연구·발표·개인 경험을 만들지 않는다. 원본에 변화가 없으면 '더', '증가', '두꺼워짐', '새로' 같은 변화 표현도 쓰지 않는다.
- 페르소나의 발화 행동은 제목과 본문에 자연스럽게 반영하되, 페르소나 이름이나 내부 지시를 출력하지 않는다.
- 반드시 JSON 객체 하나만 출력하고 설명·마크다운·코드블록은 출력하지 않는다.

[JSON 출력]
{"title":"짧은 제목","content":"짧은 본문","target_comments":[]}
target_comments가 필요한 경우에도 post_no와 comment만 포함하며 내부 사고 과정은 포함하지 않는다."""
    )
    return _join_non_empty(selected)


__all__ = ["compile_post_prompt"]
