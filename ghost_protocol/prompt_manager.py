"""Ghost Protocol — Prompt Manager

프롬프트 파일 로딩 및 변수 렌더링 유틸리티.

설계 원칙:
  - 모든 프롬프트는 UTF-8 .txt 파일로 관리 (prompts/ 디렉토리)
  - 변수 대입은 string.Template.safe_substitute() 사용
      · safe_substitute: 미정의 변수를 $varname 그대로 보존 (KeyError 없음)
      · $variable 문법은 한글·JSON 중괄호{}와 충돌하지 않음
  - lru_cache: 파일은 최초 1회만 읽고 메모리에 캐시 (재기동 전까지 유지)
  - UTF-8 강제: Windows cp949 환경에서도 한글 깨짐 없음

공개 API:
  load(name)            → raw 텍스트 반환 (변수 치환 없음)
  render(name, **kwargs) → $변수 치환 후 텍스트 반환

파일 위치:
  <project_root>/prompts/<name>
  예: prompts/system_base.txt, prompts/trend_analysis.txt
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template

# prompts/ 디렉토리: ghost_protocol/ 의 부모(프로젝트 루트) / prompts/
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@lru_cache(maxsize=None)
def _read_file(name: str) -> str:
    """프롬프트 파일을 읽어 raw 텍스트를 반환 (결과 캐시됨).

    Args:
        name: 파일명 (예: "system_base.txt")

    Raises:
        FileNotFoundError: 파일이 존재하지 않을 때 경로 힌트와 함께 발생
    """
    path = _PROMPTS_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"[PromptManager] 프롬프트 파일을 찾을 수 없습니다: {path}\n"
            f"힌트: 프로젝트 루트의 prompts/ 디렉토리와 '{name}' 파일이 존재하는지 확인하세요."
        ) from None


def load(name: str) -> str:
    """프롬프트 파일을 읽어 raw 텍스트를 반환 (변수 치환 없음).

    변수가 없는 정적 프롬프트 (예: system_base.txt) 에 사용.

    Args:
        name: 파일명 (예: "system_base.txt")

    Returns:
        파일 내용 (UTF-8 문자열)
    """
    return _read_file(name)


def render(name: str, **kwargs) -> str:
    """프롬프트 파일을 읽고 $변수를 kwargs로 치환하여 반환.

    string.Template.safe_substitute 사용:
      - 정의된 변수는 값으로 치환
      - 미정의 변수는 '$varname' 문자열 그대로 보존 (예외 없음)

    Args:
        name:     파일명 (예: "trend_analysis.txt")
        **kwargs: 치환할 변수명·값 쌍

    Returns:
        변수 치환이 완료된 프롬프트 문자열

    Example:
        >>> render("trend_analysis.txt",
        ...        gallery_id="baseball_new9",
        ...        top_k_count=20,
        ...        kw_text="오늘 경기, 선발 투수",
        ...        titles_text="- 오늘 진짜 미쳤네",
        ...        comments_text="- 진짜 ㄷㄷ")
    """
    return Template(_read_file(name)).safe_substitute(**kwargs)
