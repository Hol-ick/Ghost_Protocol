"""Ghost Protocol v5.0 — Gemini-powered post generation.

Pipeline:
  .env (GEMINI_API_KEY) → genai.Client(api_key=...)
  DB (winner posts)     → Few-shot examples (content ≤ 300 chars)
  DB (recent posts)     → Context injection ("gallery mood")
                              ↓
  Gemini 2.5 Flash → XML tag output <TITLE>…</TITLE><CONTENT>…</CONTENT>

Model: gemini-2.5-flash (무료 티어 최적)
Safety: BLOCK_NONE (전 카테고리 검열 해제)
Output: XML tag regex parsing (JSON 대비 에러 방지)
SDK: google-genai (google.genai) — 신규 공식 SDK
"""

import json
import logging
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

from . import database
from . import prompt_manager as pm

# .env 에서 GEMINI_API_KEY 로딩
load_dotenv()


# ══════════════════════════════════════════════
# API 디버그 로거 — logs/api_debug.log
# ══════════════════════════════════════════════
_LOGS_DIR = Path(__file__).parent.parent / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

_api_logger = logging.getLogger("ghost_protocol.api_debug")
_api_logger.setLevel(logging.DEBUG)

if not _api_logger.handlers:                       # Streamlit 모듈 재로딩 시 핸들러 중복 방지
    _fh = logging.FileHandler(
        _LOGS_DIR / "api_debug.log", encoding="utf-8"
    )
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    _api_logger.addHandler(_fh)
    _api_logger.propagate = False                  # 루트 로거 전파 금지 → 콘솔 오염 방지


# ══════════════════════════════════════════════
# JSON 파싱 강화 헬퍼
# ══════════════════════════════════════════════

def _parse_json_robust(text: str) -> dict:
    """Gemini 응답 텍스트에서 JSON 오브젝트를 안전하게 추출한다.

    처리 순서:
      1. 마크다운 코드펜스(```json ... ```) 내부 추출 시도
      2. 펜스가 없으면 raw 텍스트에서 첫 번째 { ... } 블록 추출
      3. json.loads() 로 파싱 — 실패 시 JSONDecodeError를 그대로 전파

    이 방식은 아래 모든 케이스를 커버한다:
      · ```json\\n{...}\\n```   (표준 마크다운)
      · ```\\n{...}\\n```       (언어 태그 없음)
      · {... }                  (펜스 없음)
      · 앞뒤 산문 + { ... }    (Gemini가 설명을 붙인 경우)
    """
    # 1단계: 마크다운 코드펜스 추출
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidate = fence_match.group(1).strip() if fence_match else text.strip()

    # 2단계: 첫 번째 { ... } 블록만 잘라냄 (앞뒤 산문 제거)
    brace_match = re.search(r"\{[\s\S]*\}", candidate)
    if brace_match:
        candidate = brace_match.group(0)

    return json.loads(candidate)

# ══════════════════════════════════════════════
# 고정 모델 (무료 티어 최적화 — Fallback 없음)
# ══════════════════════════════════════════════
MODEL_NAME = "gemini-2.5-flash"


class RateLimitError(Exception):
    """Gemini API Rate Limit (429) 또는 쿼터 초과 시 발생."""


# ══════════════════════════════════════════════
# Safety Settings: 전 카테고리 검열 해제
# ══════════════════════════════════════════════
SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
]

# ══════════════════════════════════════════════
# Jailbreak System Prompt → prompts/system_base.txt
# pm.load("system_base.txt") 로 동적 주입
# ══════════════════════════════════════════════

# content 최대 길이 (토큰 절약)
MAX_CONTENT_LENGTH = 300

# ── 댓글 길이 룰 — Phase 9: 동적 랜덤 할당 ────────────────────────────────
# generate_post() 호출마다 랜덤 선택 → $length_rule 로 generate_comment.txt 에 주입.
# 비율: 1줄(40%) / 2줄(35%) / 2~3줄(25%) — 1줄이 커뮤니티 현실에 가장 많으므로 가중치 유지.
_COMMENT_LENGTH_RULES: list[str] = [
    "딱 1줄. 짧고 강렬하게. 설명 없이 반응만 툭 던져라.",
    "딱 1줄. 짧고 강렬하게. 설명 없이 반응만 툭 던져라.",
    "2줄. 첫 줄 리액션, 둘째 줄 구체적 이유·딴지 한 마디. (줄바꿈 1회)",
    "2줄. 첫 줄 리액션, 둘째 줄 구체적 이유·딴지 한 마디. (줄바꿈 1회)",
    "2~3줄. 본문이나 기존 댓글의 디테일을 꼬투리 잡아 풀어써라. 단, 각 줄은 짧게.",
]


class GhostBrain:
    """DC Inside 스타일 게시글 생성기 -- Gemini 2.5 Flash 고정."""

    def __init__(self, api_key: Optional[str] = None):
        """Gemini 클라이언트 초기화 (google.genai 신규 SDK).

        Args:
            api_key: Gemini API key (None이면 .env에서 GEMINI_API_KEY 로딩)
        """
        key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not key:
            raise ValueError(
                "Gemini API Key가 없습니다. "
                ".env 파일에 GEMINI_API_KEY를 설정하거나 사이드바에 입력하세요."
            )
        self._client = genai.Client(api_key=key)
        self.model_name = MODEL_NAME

    # ══════════════════════════════════════════════
    # 내부 헬퍼
    # ══════════════════════════════════════════════

    def _get_gallery_context(self, gallery_id: str) -> str:
        """갤러리 ID → 고유 문법 룰 + 퓨샷 예시 프롬프트 블록 반환.

        라우팅 우선순위:
          1. gallery_contexts.json에서 gallery_id 정확 매치
          2. 포함 관계 매치 (key in gallery_id OR gallery_id in key)
          3. "default" 폴백

        토큰 최적화:
          - 문법 룰 최대 3개, 퓨샷 최대 2개, 본문 80자 제한
          - 빈 컨텍스트(default fewshot=[])는 룰만 반환 → ~150 토큰 이하
        """
        ctx_db: dict = pm.load_json("gallery_contexts.json")

        # 1차: 정확 매치
        ctx = ctx_db.get(gallery_id)

        # 2차: 부분 포함 매치 (_로 시작하는 메타 키 제외)
        if ctx is None:
            for key, val in ctx_db.items():
                if key.startswith("_"):
                    continue
                if key in gallery_id or gallery_id in key:
                    ctx = val
                    break

        # 3차: default 폴백
        if ctx is None:
            ctx = ctx_db.get("default", {})

        gallery_name = ctx.get("gallery_name", gallery_id)
        rules: list[str] = ctx.get("grammar_rules", [])
        fewshot: list[dict] = ctx.get("fewshot", [])

        # 컨텍스트가 비어있으면 주입하지 않음
        if not rules and not fewshot:
            return ""

        lines = [f"[🏠 {gallery_name} 고유 언어 룰 — 이 갤에서만 통하는 문법]"]
        for i, rule in enumerate(rules[:3], 1):
            lines.append(f"  {i}. {rule}")

        if fewshot:
            lines.append(f"\n[{gallery_name} 실제 글 스타일 샘플 (말투만 참고 — 내용 복사 절대 금지)]")
            for ex in fewshot[:2]:
                t = ex.get("title", "")
                c = (ex.get("content", "") or "")[:80]
                lines.append(f"  제목: {t}")
                if c:
                    lines.append(f"  본문: {c}")

        return "\n".join(lines)

    def _get_style_examples(self, gallery_id: str, n: int = 3) -> list[dict]:
        """DB에서 is_winner=True 글 N개를 Few-shot 예시로 가져옴.

        본문(content)은 MAX_CONTENT_LENGTH(300자)로 잘라서 토큰 절약.
        """
        raw = database.get_winner_posts(gallery_id, limit=n)
        for ex in raw:
            content = ex.get("content", "")
            if len(content) > MAX_CONTENT_LENGTH:
                ex["content"] = content[:MAX_CONTENT_LENGTH] + "..."
        return raw

    def _get_current_context(
        self, gallery_id: str, hours: int = 1
    ) -> list[dict]:
        """최근 N시간 게시글로 '갤러리 분위기' 파악."""
        return database.get_recent_posts(gallery_id, hours=hours)

    @staticmethod
    def _is_rate_limit_error(err: Exception) -> bool:
        """429 / ResourceExhausted 에러 판별."""
        err_str = str(err).lower()
        return (
            "429" in err_str
            or "resource" in err_str and "exhausted" in err_str
            or "quota" in err_str
            or "rate" in err_str and "limit" in err_str
        )

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def suggest_topic(
        self,
        gallery_id: str,
        context_hours: float = 1.0,
        keywords: Optional[list[str]] = None,
    ) -> str:
        """최근 글 제목 + 핫 키워드를 바탕으로 자극적인 게시글 주제 1개를 추천.

        Args:
            gallery_id: 갤러리 ID
            context_hours: 참조할 시간 범위 (기본 1시간)
            keywords: 실시간 핫 키워드 리스트 (None이면 제목만 참조)

        Returns:
            추천 주제 문자열 (에러 시 기본값 반환)
        """
        recent = self._get_current_context(gallery_id, hours=int(max(context_hours, 1)))
        if not recent:
            return "수집된 데이터가 없습니다. 먼저 스캔을 실행하세요."

        titles = [p.get("title", "") for p in recent[:20]]
        titles_text = "\n".join(f"- {t}" for t in titles if t)

        # 키워드 유무에 따라 템플릿 분기 (prompts/ 디렉토리에서 로딩)
        if keywords and len(keywords) > 0:
            kw_text = ", ".join(keywords[:15])
            prompt = pm.render(
                "suggest_topic_kw.txt",
                kw_text=kw_text,
                titles_text=titles_text,
            )
        else:
            prompt = pm.render(
                "suggest_topic_nokw.txt",
                titles_text=titles_text,
            )

        try:
            _cfg = types.GenerateContentConfig(
                system_instruction=pm.render("system_base.txt", gallery_id=gallery_id),
                safety_settings=SAFETY_SETTINGS,
                response_mime_type="application/json",  # Native JSON — 마크다운 펜스 원천 차단
                temperature=0.9,
                max_output_tokens=200,   # 50 → 200 (JSON 래퍼 + 한글 주제 잘림 방지)
            )
            response = self._client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=_cfg,
            )
            # 디버깅: 원시 응답 출력
            raw_text = response.text.strip()
            print(f"[DEBUG] suggest_topic Raw AI Response: '{raw_text}'")

            # 강화된 JSON 파싱 후 topic 추출
            try:
                data = _parse_json_robust(raw_text)
                topic = data.get("topic", "").strip()
                print(f"[DEBUG] suggest_topic JSON parsed OK")
            except (json.JSONDecodeError, AttributeError):
                # JSON 파싱 실패 시 첫 줄 fallback
                lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                topic = lines[0] if lines else raw_text
                topic = re.sub(r'["\'\*`#{}:\[\]]', '', topic)
                topic = re.sub(r'(?i)^(topic|제목|주제)\s*', '', topic).strip()

            print(f"[DEBUG] suggest_topic Parsed: '{topic}'")
            return topic if topic else "갤러리 떡밥"

        except Exception as e:
            if self._is_rate_limit_error(e):
                return "[Rate Limit] 1분 뒤에 다시 시도하세요"
            return "갤러리 떡밥"

    def generate_post(
        self,
        topic: str,
        gallery_id: str,
        tone: str = "cynical",
        context_hours: Optional[int] = 1,
        length: str = "보통 (3~4문장)",
        keywords: Optional[list[str]] = None,
        recent_posts: Optional[list[dict]] = None,
    ) -> dict:
        """DC Inside 스타일 게시글 생성 + 소셜 인터랙션 댓글 콤보.

        Args:
            topic: 글 주제 (예: "요즘 분위기 왜 이러냐")
            gallery_id: 갤러리 ID (예: "baseball_new9")
            tone: 말투 (cynical / neutral / analytical / aggressive)
            context_hours: 컨텍스트 시간 범위 (None이면 미사용)
            length: 글 길이 ("짧게 (1~2문장)" / "보통 (3~4문장)" / "길게 (5문장 이상)")
            keywords: 핫 키워드 리스트 (본문 살 붙이기용)
            recent_posts: 댓글 타겟 후보 목록 (봇 게시글 제외).
                          각 dict: {"post_no": str, "title": str}
                          None이면 댓글 타겟 없이 포스팅만 생성.

        Returns:
            {
              "title":           str,
              "content":         str,
              "target_comments": [{"post_no": str, "comment": str}, ...],
            }
            파싱 실패 시: {"title": "", "content": "", "_parse_error": True, ...}
        """
        # ── 톤·분량 지시문 — prompts/tones.json / lengths.json 에서 로드 ──────
        tone_desc   = pm.load_json("tones.json")
        length_desc = pm.load_json("lengths.json")

        # ── 프롬프트 조립 ──
        parts = []

        # Few-shot: 념글 예시 (content 300자 truncate 적용)
        examples = self._get_style_examples(gallery_id)
        if examples:
            examples_text = "\n\n".join(
                f"[념글 예시 {i + 1}]\n제목: {ex.get('title', '')}\n"
                f"본문: {ex.get('content', '')}"
                for i, ex in enumerate(examples)
            )
            parts.append(
                "아래는 추천 많이 받은 글(념글) 예시야. "
                "이 말투와 분위기를 그대로 따라해:\n\n" + examples_text
            )

        # Context: 갤러리 분위기 (제목만, 최대 10개로 축소)
        if context_hours and context_hours > 0:
            recent = self._get_current_context(gallery_id, hours=context_hours)
            if recent:
                titles = [p.get("title", "") for p in recent[:10]]
                context_text = "\n".join(f"- {t}" for t in titles if t)
                parts.append(
                    f"현재 갤러리 분위기 (최근 {context_hours}시간 글 제목):\n"
                    + context_text
                )

        # User prompt (XML 태그 출력 강제 + 길이/톤 조건)
        tone_instruction = tone_desc.get(tone, tone_desc["cynical"])
        length_instruction = length_desc.get(length, length_desc["보통 (3~4문장)"])

        # 키워드 떡밥 주입 (분위기 파악용 — 욱여넣기 방지)
        kw_inject = ""
        if keywords and len(keywords) > 0:
            kw_text = ", ".join(keywords[:10])
            kw_inject = (
                f"\n[갤러리 분위기 키워드 (참고용): {kw_text}]\n"
                "⚠️ 이 키워드는 갤러리 분위기 파악용이다. 전부 쓰거나 나열하면 절대 안 된다.\n"
                "이 중 딱 1개, 글에 자연스럽게 녹아드는 것만 골라 써라. 0개 써도 된다.\n"
                "키워드 나열 = 최악의 AI 냄새다. 절대 금지.\n"
            )

        # ── 교차 지시 — prompts/cross_instructions.json 에서 로드 ────────────
        # 규칙: tone 키가 cross_instructions.json에 있으면 자동 적용.
        # 특수 조합(monologue × 아주 짧게)은 별도 키로 오버라이드.
        _cross = pm.load_json("cross_instructions.json")
        cross_instruction = _cross.get(tone, "")   # 모든 페르소나 tone 자동 적용
        if tone == "monologue" and length == "아주 짧게 (1문장)":
            cross_instruction = _cross.get("monologue_ultrashort", cross_instruction)

        # ── 댓글 타겟 컨텍스트 빌드 ─────────────────────────────────────────
        # recent_posts 각 항목: {"post_no": str, "title": str, "existing_comments": list[str]}
        # existing_comments: 호출자(app.py)가 AJAX로 프리패치한 기존 댓글 (최대 5개, 없으면 [])
        # post_no 검증은 파서 단계에서 수행 (hallucination 방어).
        if recent_posts:
            # Phase 9: 댓글 길이 룰 랜덤 선택 — 봇마다 대사 길이 변주
            _comment_length_rule = random.choice(_COMMENT_LENGTH_RULES)
            _posts_formatted: list[str] = []
            for p in recent_posts:
                _line = f"#{p.get('post_no', '?')} | {p.get('title', '')}"
                _existing = p.get("existing_comments", [])
                if _existing:
                    _cmt_sample = " / ".join(f'"{c[:40]}"' for c in _existing[:3])
                    _line += f"\n  └ 기존 댓글: {_cmt_sample}"
                _posts_formatted.append(_line)
            recent_posts_context = pm.render(
                "generate_comment.txt",
                posts_context="\n".join(_posts_formatted),
                length_rule=_comment_length_rule,
            )
        else:
            recent_posts_context = ""

        # ── 갤러리 고유 언어 컨텍스트 — Dynamic Routing ──────────────────────
        # gallery_contexts.json에서 gallery_id로 조회한 문법 룰 + 퓨샷 블록.
        # 주입 위치: generate_post.txt 바로 앞 → LLM 어텐션 최근접 보장.
        # 토큰 예산: 룰 3개 + 퓨샷 2개 = 최대 ~250 토큰 (generate_post.txt의 ~15%)
        _gal_ctx = self._get_gallery_context(gallery_id)
        if _gal_ctx:
            parts.append(_gal_ctx)

        # ── 작문 지시 — prompts/generate_post.txt 에서 로드 ──────────────────
        # 하드코딩 제로: 분량·톤·키워드·교차지시를 템플릿 변수로 주입.
        # 사용자는 generate_post.txt 만 수정하면 작문 스타일 전체를 튜닝 가능.
        parts.append(
            pm.render(
                "generate_post.txt",
                gallery_id=gallery_id,
                topic=topic,
                tone_instruction=tone_instruction,
                length_instruction=length_instruction,
                cross_instruction=cross_instruction,
                kw_inject=kw_inject,
                recent_posts_context=recent_posts_context,
            )
        )

        prompt = "\n\n---\n\n".join(parts)

        # ── Gemini API 호출 (GenerateContentConfig + 429 안전 처리) ──
        # analyze_trend()와 동일한 방어벽:
        #   response_mime_type="application/json" → 마크다운 펜스 원천 차단
        #   response_schema                       → title/content 구조 고정, key 누락 불가
        #   thinking_budget=0                     → thinking 토큰의 max_output_tokens 잠식 방지
        _POST_SCHEMA = {
            "type": "object",
            "properties": {
                "_thought_process": {
                    "type": "object",
                    "description": "대사 생성 전 필수 사전 계획. title/content보다 반드시 먼저 채워라.",
                    "properties": {
                        "target_noun": {
                            "type": "string",
                            "description": "브리핑에서 훔쳐온 구체적 명사 1개 (인물명/팀명/사건명/숫자)",
                        },
                        "persona_metaphor": {
                            "type": "string",
                            "description": "페르소나를 '바닥이다/망했다/개좋다/터진다' 같은 클리셰 없이 일상 비유로 표현한 한 문장",
                        },
                        "start_style": {  # <-- 여기 변경
                            "type": "string",
                            "description": "본문을 시작하는 방식. 첫 단어가 반드시 '아니/아/하/다들/에휴/진짜' 이외여야 한다. (예: target_noun 직격, 숫자 직격, 동사 직격, 욕설 초성 등 매번 다르게 설정)",
                        },
                    },
                    "required": ["target_noun", "persona_metaphor", "start_style"], # <-- 여기 변경
                },
                "title": {
                    "type": "string",
                    "description": "갤러리 게시글 제목. 길이 제한 없음. 툭 던지는 짧은 단어부터 감정을 주체 못 하고 구구절절 늘어놓는 긴 제목까지 매번 길이를 무작위로 다르게 설정해라. 마침표 금지.",
                },
                "content": {
                    "type": "string",
                    "description": "갤러리 게시글 본문 (1~2줄 초단문, 마침표 금지). 첫 문장은 _thought_process.start_style 방식을 따라야 한다.", # <-- 여기 변경
                },
                "target_comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "_thought_process": {
                                "type": "object",
                                "description": "댓글 생성 전 필수 사전 계획. comment보다 반드시 먼저 채워라.",
                                "properties": {
                                    "target_noun": {
                                        "type": "string",
                                        "description": "게시글에서 꼬투리 잡을 구체적 명사 1개",
                                    },
                                    "reused_word": {
                                        "type": "string",
                                        "description": "기존 댓글에 이미 쓰인 핵심 단어. 이 단어를 comment에 그대로 쓰지 않는다",
                                    },
                                    "start_style": { # <-- 여기 변경
                                        "type": "string",
                                        "description": "댓글을 시작하는 방식. 첫 단어가 반드시 '아니/아/하/다들/에휴/진짜' 이외여야 한다. (예: 본문 내용 반박, 동조하는 욕설, 다짜고짜 비웃기 등)",
                                    },
                                },
                                "required": ["target_noun", "reused_word", "start_style"], # <-- 여기 변경
                            },
                            "post_no": {
                                "type": "string",
                                "description": "댓글을 달 DC Inside 게시글 번호 (숫자 문자열)",
                            },
                            "comment": {
                                "type": "string",
                                "description": "작성할 댓글 내용 (길이 룰에 따라 변동). 시작은 _thought_process.start_style 방식을 따라야 한다. 마침표 금지.", # <-- 여기 변경
                            },
                        },
                        "required": ["_thought_process", "post_no", "comment"],
                        "propertyOrdering": ["_thought_process", "post_no", "comment"],
                    },
                    "description": "댓글 타겟 목록 — 서로 다른 게시글 최대 2개. 같은 post_no는 반드시 1번만 등장. 타겟 없으면 빈 배열.",
                },
            },
            "required": ["_thought_process", "title", "content", "target_comments"],
            "propertyOrdering": ["_thought_process", "title", "content", "target_comments"],
        }
        _cfg = types.GenerateContentConfig(
            system_instruction=pm.render("system_base.txt", gallery_id=gallery_id),
            safety_settings=SAFETY_SETTINGS,
            response_mime_type="application/json",
            response_schema=_POST_SCHEMA,
            max_output_tokens=2048,
            temperature=0.9,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        try:
            response = self._client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=_cfg,
            )
        except Exception as e:
            if self._is_rate_limit_error(e):
                # 에러 dict 반환 대신 명시적 예외 발생 — 호출자가 재시도 여부를 결정 (Flaw #2 수정)
                raise RateLimitError(
                    "Gemini API Rate Limit 초과 (429). 잠시 후 재시도 필요."
                ) from e
            raise  # 다른 에러는 그대로 상위로 전파

        # ── Debug: 중단 원인 로깅 ──
        try:
            # 1=STOP(정상), 2=MAX_TOKENS(길이초과), 3=SAFETY(검열)
            finish_reason = response.candidates[0].finish_reason
            print(f"[DEBUG] Generation Finish Reason: {finish_reason}")
        except Exception:
            pass

        # ── JSON 전용 파서 (Native JSON Mode 강제 적용) ──────────────────────
        # response_mime_type="application/json" 적용으로 마크다운 펜스 원천 차단.
        # 파싱 실패 = 구조적 이상 (빈 응답, 검열 등) → _parse_error Abort 신호 반환.
        # "무제" + 원본 텍스트 포스팅 버그 완전 제거.
        raw_text = response.text.strip()

        # ── 로그: Raw 응답 + finish_reason 기록 ──────────────────────────────
        _finish_reason = (
            str(response.candidates[0].finish_reason)
            if response.candidates else "UNKNOWN"
        )
        _api_logger.debug(
            "generate_post RESPONSE ▶ len=%d finish_reason=%s\n%s\n%s",
            len(raw_text), _finish_reason, "─" * 60, raw_text,
        )
        if _finish_reason != "FinishReason.STOP":
            _api_logger.warning(
                "generate_post NON-STOP finish_reason=%s — 응답 잘림 또는 필터링 가능성",
                _finish_reason,
            )

        try:
            _json_out = _parse_json_robust(raw_text)
            title   = str(_json_out.get("title",   "")).strip()
            content = str(_json_out.get("content", "")).strip()

            # ── target_comments: 실패해도 Wave Abort 없이 빈 배열로 safe fallback ──
            # post_no가 숫자 문자열인 항목만 허용 → hallucinated/invalid ID 원천 차단
            # Phase 10: 동일 post_no 댓글 연사 방지 — dict 순서를 보존하며 병합.
            # LLM이 2줄 댓글을 같은 post_no로 2개 반환하면 → "\n"으로 합쳐 1개로 정규화.
            _tc_raw = _json_out.get("target_comments", [])
            _tc_merged: dict[str, str] = {}
            for _tc_item in (_tc_raw if isinstance(_tc_raw, list) else []):
                if not isinstance(_tc_item, dict):
                    continue
                _pno = str(_tc_item.get("post_no", "")).strip()
                _cmt = str(_tc_item.get("comment", "")).strip()
                if not _pno.isdigit() or not _cmt:
                    continue
                if _pno in _tc_merged:
                    _tc_merged[_pno] = _tc_merged[_pno] + "\n" + _cmt  # 연사 → 1개 병합
                else:
                    _tc_merged[_pno] = _cmt
            target_comments: list[dict] = [
                {"post_no": k, "comment": v}
                for k, v in list(_tc_merged.items())[:2]  # 서로 다른 게시글 최대 2개 상한
            ]

        except Exception as _exc:
            _api_logger.error(
                "generate_post PARSE ERROR ▶ %s\nRAW (len=%d):\n%s",
                _exc, len(raw_text), raw_text,
            )
            return {"title": "", "content": "", "target_comments": [], "_parse_error": True, "_raw_response": raw_text}

        # ── score_reporter: Python 레벨 숫자 검증 ─────────────────────────────
        # cross_instruction에서 수치 강제했음에도 LLM이 누락하는 경우 reject.
        # re.search(r'\d', content) → 아라비아 숫자 하나라도 있으면 통과.
        if tone == "score_reporter" and not re.search(r"\d", content):
            _api_logger.warning(
                "generate_post SCORE_REPORTER NO_DIGIT ▶ content에 숫자 없음 → reject\ncontent: %r",
                content,
            )
            return {"title": "", "content": "", "target_comments": [], "_parse_error": True, "_raw_response": raw_text}

        if not title or not content:
            _api_logger.warning(
                "generate_post EMPTY FIELD ▶ title=%r content=%r\nRAW:\n%s",
                title, content, raw_text,
            )
            return {"title": "", "content": "", "target_comments": [], "_parse_error": True, "_raw_response": raw_text}

        return {
            "title":           title,
            "content":         content,
            "target_comments": target_comments,
        }

    # ══════════════════════════════════════════════
    # INTEL 트렌드 분석 (Read-Only — 포스팅 없음)
    # ══════════════════════════════════════════════

    def analyze_trend(
        self,
        raw_data: dict,
        top_k: int = 30,
    ) -> dict:
        """수집된 Raw 데이터로 갤러리 트렌드를 분석하여 JSON 반환.

        Pipeline:
          raw_data (titles + comments)
            → Counter 기반 Top-K 키워드 추출 (불용어 제거)
            → 대표 댓글 샘플 최대 15개 (각 50자 trim)
            → 키워드 + 샘플만 Gemini 2.5 Flash 로 전달 (토큰 최소화)
            → JSON 파싱 후 반환

        Args:
            raw_data: TrendScraper.collect_trending() 반환값
                      {"titles": [...], "comments": [...], "gallery_id": "...", ...}
            top_k:    추출할 핵심 키워드 수 (기본 30)

        Returns:
            {
              "hot_topics":   list[str],   # 현재 핫한 떡밥 3개
              "sentiment":    str,         # 전반적인 감성 (우호적/적대적/조롱/패닉 등)
              "memes":        list[str],   # 유행하는 밈·유행어
              "summary":      str,         # 2문장 갤러리 분위기 요약
              "top_keywords": list[str],   # Counter 추출 Top-K 키워드
              "stats":        dict,        # 수집 통계
            }
        """
        from .config import KEYWORD_STOPWORDS

        titles:   list[str] = raw_data.get("titles",   [])
        comments: list[str] = raw_data.get("comments", [])
        authors:  list[str] = raw_data.get("authors",  [])

        # ── 봇 점유율 계산 ──────────────────────────────────────────────────
        # scraper.collect_trending()이 주입한 ai_post_count / total_post_count를 사용.
        # ledger 기반 집계: 로컬 bot_ledger.json 대조로 정확도 보장.
        _ai_post_count    = raw_data.get("ai_post_count",    0)
        _total_post_count = raw_data.get("total_post_count", 0)
        if _total_post_count > 0:
            _ai_pct  = _ai_post_count / _total_post_count * 100
            ai_share = f"{_ai_post_count}/{_total_post_count}개 ({_ai_pct:.1f}%)"
        else:
            ai_share = "데이터 없음"

        # ── 1. 모든 텍스트 합치기 ──────────────────────────
        all_text = " ".join(titles + comments)

        # ── 2. 한글 토큰 추출 (2자 이상 한글 어절) ─────────
        tokens = re.findall(r"[가-힣]{2,}", all_text)

        # ── 3. 불용어 제거 + Counter ───────────────────────
        filtered    = [t for t in tokens if t not in KEYWORD_STOPWORDS]
        counter     = Counter(filtered)
        top_keywords: list[str] = [w for w, _ in counter.most_common(top_k)]

        # ── 4. Author Dominance 계산 ────────────────────────
        # 작성자 점유율 Top 5 → "$author_stats" 변수로 Gemini에 전달
        # 예: "김사자(80%), ㅇㅇ(10%), 홍길동(5%), 익명(3%), 기타(2%)"
        author_stats = "데이터 없음"
        if authors:
            author_counter = Counter(a for a in authors if a)
            total_authors = sum(author_counter.values())
            if total_authors > 0:
                top_authors = author_counter.most_common(5)
                parts = [
                    f"{name}({count / total_authors * 100:.0f}%)"
                    for name, count in top_authors
                ]
                author_stats = ", ".join(parts)

        # ── 5. Gemini 전달용 경량 페이로드 조립 ────────────
        # 제목 샘플: 최대 20개
        kw_text     = ", ".join(top_keywords[:20])
        titles_text = "\n".join(f"- {t}" for t in titles[:20])
        # 댓글 샘플: 최대 15개 × 50자 trim
        comments_text = "\n".join(
            f"- {c[:50]}" for c in comments[:15]
        )

        gallery_id = raw_data.get("gallery_id", "알 수 없음")

        prompt = pm.render(
            "trend_analysis.txt",
            gallery_id=gallery_id,
            top_k_count=min(len(top_keywords), 20),
            kw_text=kw_text,
            titles_text=titles_text,
            comments_text=comments_text,
            author_stats=author_stats,
            ai_share=ai_share,
        )

        # ── 6. Gemini API 호출 (분석용 — Native JSON Mode + Schema 강제) ──
        # response_mime_type: API 레벨 순수 JSON 강제 → 마크다운 펜스 원천 차단
        # response_schema:    반환 구조·타입 고정 → key 누락·임의 구조 변경 불가
        # max_output_tokens:  2048 (hot_topics/summary 잘림 방지)
        _TREND_SCHEMA = {
            "type": "object",
            "properties": {
                "hot_topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "현재 갤러리에서 가장 핫한 떡밥 3개",
                },
                "sentiment": {
                    "type": "string",
                    "description": "전반적인 갤러리 감성 (우호적/적대적/조롱/패닉 등)",
                },
                "memes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "유행하는 밈·유행어",
                },
                "summary": {
                    "type": "string",
                    "description": "2문장 갤러리 분위기 요약",
                },
                "ai_analysis": {
                    "type": "string",
                    "description": "갤러리의 전반적인 분위기와 민심에 대한 AI의 평문 분석 요약",
                },
            },
            "required": ["hot_topics", "sentiment", "memes", "summary", "ai_analysis"],
        }
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_TREND_SCHEMA,
            max_output_tokens=8192,                              # 2048 → 8192: 안전 마진 4× 확장
            temperature=0.3,                                     # 분석 태스크 → 낮은 온도 = 일관성 ↑
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            # ↑ gemini-2.5-flash 기본 thinking 비활성화:
            #   thinking 토큰이 max_output_tokens 예산을 잠식해
            #   ~516chars 부근에서 응답이 잘리는 현상의 근본 원인.
            #   이 태스크는 구조화된 JSON 추출 → 창의적 사고 불필요.
        )

        raw_text = ""
        try:
            # ── 로그: Gemini에 보내는 프롬프트 전문 기록 ──────────────────────
            _api_logger.debug(
                "analyze_trend PROMPT ▶ gallery=%s\n%s\n%s",
                gallery_id, "─" * 60, prompt,
            )

            response = self._client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=cfg,
            )
            raw_text = response.text.strip()

            # ── 로그: Gemini Raw 응답 + finish_reason 기록 ────────────────────
            _finish_reason = (
                str(response.candidates[0].finish_reason)
                if response.candidates else "UNKNOWN"
            )
            _api_logger.debug(
                "analyze_trend RESPONSE ▶ len=%d finish_reason=%s\n%s\n%s",
                len(raw_text), _finish_reason, "─" * 60, raw_text,
            )
            # finish_reason != STOP → 잘림/안전필터 경고 (MAX_TOKENS 포함)
            if _finish_reason != "FinishReason.STOP":
                _api_logger.warning(
                    "analyze_trend NON-STOP finish_reason=%s — 응답 잘림 또는 필터링 가능성",
                    _finish_reason,
                )

            # 강화된 JSON 파싱 (마크다운 펜스 + 앞뒤 산문 제거)
            result = _parse_json_robust(raw_text)

        except json.JSONDecodeError as _exc:
            # ── 로그: 파싱 실패 상세 기록 ─────────────────────────────────────
            _api_logger.error(
                "analyze_trend PARSE ERROR ▶ %s\nRAW RESPONSE (len=%d):\n%s\n%s",
                _exc, len(raw_text), "─" * 60, raw_text,
            )
            print(
                f"[RAW RESPONSE] analyze_trend JSON parse failed "
                f"(len={len(raw_text)} chars):\n{raw_text}",
                flush=True,
            )
            # 안전한 기본 딕셔너리 반환 — UI 붕괴 방지
            # _parse_error / _raw_response: app.py 디버그 뷰어가 감지·표시
            result = {
                "hot_topics":    top_keywords[:3],
                "sentiment":     "분석 실패",
                "memes":         [],
                "summary":       "N/A",
                "ai_analysis":   "⚠️ API 응답 파싱 실패 — logs/api_debug.log 를 확인하세요.",
                "_parse_error":  True,
                "_raw_response": raw_text,
            }
        except Exception as e:
            if self._is_rate_limit_error(e):
                raise RateLimitError(
                    "Gemini API Rate Limit 초과 (429). 잠시 후 재시도 필요."
                ) from e
            raise

        # ── 7. 공통 메타데이터 주입 ─────────────────────────
        result["top_keywords"] = top_keywords
        # keyword_counts: Plotly 빈도 차트용 (word → 실제 등장 횟수)
        result["keyword_counts"] = dict(counter.most_common(top_k))
        result["author_stats"] = author_stats   # author dominance 요약 문자열
        result["ai_share"]     = ai_share       # ledger 기반 봇 점유율 문자열
        result["stats"] = {
            "titles_count":    len(titles),
            "comments_count":  len(comments),
            "authors_count":   len(authors),
            "keywords_found":  len(filtered),
            "ai_post_count":   _ai_post_count,
            "total_post_count": _total_post_count,
        }
        # 원본 게시글 목록 pass-through (UI 디버깅용, analyze_trend에서 가공 안 함)
        result["raw_posts"] = raw_data.get("raw_posts", [])

        return result
