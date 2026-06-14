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
from .content_filter import (
    filter_noise_strings,
    sanitize_analysis_keywords,
    sanitize_sensitive_target_comments,
    sanitize_user_drama_text,
    sensitive_generation_violations,
)
from .application import gemini_throttle
from .domain import gallery_purpose, gallery_style, naturalness

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
MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
FALLBACK_MODEL_NAMES = tuple(
    model
    for model in (
        item.strip()
        for item in os.getenv(
            "GEMINI_FALLBACK_MODELS",
            "gemini-2.5-flash-lite",
        ).split(",")
    )
    if model and model != MODEL_NAME
)


class RateLimitError(Exception):
    """Gemini API Rate Limit (429) 또는 쿼터 초과 시 발생."""


# ══════════════════════════════════════════════
# Safety Settings: 전 카테고리 검열 해제
# ══════════════════════════════════════════════
def _shorten_log_value(value: object, *, limit: int = 800) -> str:
    """Return a compact, single-line representation for API diagnostics."""

    try:
        text = str(value)
    except Exception:
        text = repr(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",       threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
]

# ══════════════════════════════════════════════
# System prompt → prompts/system_base.txt
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
        try:
            http_timeout_ms = int(os.getenv("GEMINI_HTTP_TIMEOUT_MS", "35000"))
        except (TypeError, ValueError):
            http_timeout_ms = 35000
        http_timeout_ms = max(5000, min(120000, http_timeout_ms))
        self._client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=http_timeout_ms),
        )
        self.model_name = MODEL_NAME
        self.fallback_model_names = FALLBACK_MODEL_NAMES

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

    @staticmethod
    def _describe_exception(err: Exception) -> str:
        """Extract useful SDK error details without crashing logging."""

        parts: list[str] = []
        for attr in ("status_code", "code", "message", "details"):
            if not hasattr(err, attr):
                continue
            try:
                value = getattr(err, attr)
            except Exception:
                continue
            if value:
                parts.append(f"{attr}={_shorten_log_value(value)}")

        response = getattr(err, "response", None)
        if response is not None:
            for attr in ("status_code", "text", "content"):
                try:
                    value = getattr(response, attr, None)
                except Exception:
                    value = None
                if value:
                    parts.append(f"response.{attr}={_shorten_log_value(value)}")

        if not parts:
            parts.append(_shorten_log_value(err))
        return " | ".join(parts)

    def _generate_content_paced(self, *, label: str, **kwargs):
        """Call Gemini through the shared throttle, with model fallback on 429."""

        requested_model = kwargs.get("model") or self.model_name
        fallback_models = tuple(getattr(self, "fallback_model_names", ()) or ())
        models_to_try = [requested_model]
        models_to_try.extend(
            model for model in fallback_models if model and model != requested_model
        )

        last_rate_limit: Exception | None = None
        for index, model_name in enumerate(models_to_try):
            call_kwargs = dict(kwargs)
            call_kwargs["model"] = model_name
            call_label = f"{label}:{model_name}"

            waited = gemini_throttle.wait_before_call(call_label)
            if waited >= 0.5:
                _api_logger.debug(
                    "gemini throttle wait %.2fs before %s",
                    waited,
                    call_label,
                )
            if index > 0:
                _api_logger.warning(
                    "gemini fallback model selected label=%s model=%s after=%s",
                    label,
                    model_name,
                    requested_model,
                )

            try:
                return self._client.models.generate_content(**call_kwargs)
            except Exception as err:
                if not self._is_rate_limit_error(err):
                    raise

                last_rate_limit = err
                _api_logger.warning(
                    "gemini rate limit label=%s model=%s detail=%s repr=%s",
                    label,
                    model_name,
                    self._describe_exception(err),
                    _shorten_log_value(repr(err)),
                )

                if index < len(models_to_try) - 1:
                    gemini_throttle.note_rate_limit_pause(5.0)
                    continue
                gemini_throttle.note_rate_limit_pause(60.0)

        if last_rate_limit is not None:
            raise last_rate_limit
        raise RuntimeError("No Gemini model configured")

    # ══════════════════════════════════════════════
    # 공개 API
    # ══════════════════════════════════════════════

    def suggest_topic(
        self,
        gallery_id: str,
        context_hours: float = 1.0,
        keywords: Optional[list[str]] = None,
    ) -> str:
        """최근 글 제목 + 핫 키워드를 바탕으로 후속 초안 주제 1개를 추천.

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
            response = self._generate_content_paced(
                label="suggest_topic",
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

        # ── 페르소나 심화 프로필 — 관심 도메인 + 어휘 스타일 주입 ──────────
        _profiles = pm.load_json("persona_profiles.json")
        _prof = _profiles.get(tone)
        if _prof:
            _domain = ", ".join(_prof.get("domain_affinity", []))
            _vstyle = _prof.get("vocab_style", "")
            _never  = ", ".join(_prof.get("never_say", []))
            _good_moves = " / ".join(_prof.get("good_moves", []))
            _bad_moves = " / ".join(_prof.get("bad_moves", []))
            tone_instruction += (
                f"\n[페르소나 심화] 관심 도메인: {_domain}. "
                f"어휘 스타일: {_vstyle}. "
                f"좋은 발화 동작: {_good_moves}. "
                f"피해야 할 동작: {_bad_moves}. "
                f"절대 쓰지 않는 표현: {_never}."
            )

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

        # Persona behavior now has one source of truth: persona_profiles.json.
        # The previous cross-instruction + policy-persona overlays repeated the
        # same prohibitions in slightly different words and pushed every role
        # toward the same cautious question template.
        cross_instruction = ""

        # ── 댓글 타겟 컨텍스트 빌드 ─────────────────────────────────────────
        # recent_posts 각 항목:
        # {"post_no": str, "title": str, "content": str, "existing_comments": list[str]}
        # existing_comments: 호출자(app.py)가 AJAX로 프리패치한 기존 댓글 (최대 5개, 없으면 [])
        # post_no 검증은 파서 단계에서 수행 (hallucination 방어).
        if recent_posts:
            # Phase 9: 댓글 길이 룰 랜덤 선택 — 봇마다 대사 길이 변주
            _comment_length_rule = random.choice(_COMMENT_LENGTH_RULES)
            _posts_formatted: list[str] = []
            for p in recent_posts:
                _line = f"#{p.get('post_no', '?')} | {p.get('title', '')}"
                _content = str(p.get("content") or "").strip()
                if _content:
                    _line += f"\n  └ 본문: {_content[:80]}"
                _existing = p.get("existing_comments", [])
                if _existing:
                    _cmt_sample = " / ".join(f'"{c[:28]}"' for c in _existing[:2])
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
                naturalness_policy=naturalness.generation_policy_block(),
                naturalness_final_check=naturalness.final_check_block(),
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
                            "description": "브리핑에서 고른 구체 소재 1개. 안전 치환어가 있으면 사람 이름이 아니라 표현·장면·사건·숫자·물건을 고른다.",
                        },
                        "persona_metaphor": {
                            "type": "string",
                            "description": "페르소나의 발화 행동을 내부 메모로 설명한다. 이 문장을 title/content에 복사하지 않는다.",
                        },
                        "start_style": {  # <-- 여기 변경
                            "type": "string",
                            "description": "본문을 시작하는 호흡. 같은 접속사나 첫 단어를 반복하지 않는다. 예: 장면 직격, 구체 행동, 짧은 판단, 경험 회상, 낮은 반박 등. 질문형은 예외적으로만 쓴다.",
                        },
                        "slot_used": {
                            "type": "string",
                            "description": "target_noun의 출처 슬롯. A/B/C/R/G/context 중 정확히 하나.",
                        },
                    },
                    "required": ["target_noun", "persona_metaphor", "start_style", "slot_used"], # <-- 여기 변경
                },
                "title": {
                    "type": "string",
                    "description": "갤러리 게시글 제목. 한 가지 장면이나 판단을 자연스러운 길이로 쓴다. 질문형·빈도 불평형 제목은 드물게만 쓰고 마침표는 붙이지 않는다.",
                },
                "content": {
                    "type": "string",
                    "description": "갤러리 게시글 본문. 기본 1줄, 필요한 경우만 2줄. 제목을 다시 말하지 말고 구체 장면·근거·반응 중 하나를 더한다. 마침표는 붙이지 않는다.", # <-- 여기 변경
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
                                        "description": "댓글을 시작하는 호흡. 타겟 글에 반응하되 같은 접속사와 같은 첫 단어를 반복하지 않는다.",
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
            temperature=0.78,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        try:
            response = self._generate_content_paced(
                label="generate_post",
                model=MODEL_NAME,
                contents=prompt,
                config=_cfg,
            )
        except Exception as e:
            if self._is_rate_limit_error(e):
                # 에러 dict 반환 대신 명시적 예외 발생 — 호출자가 재시도 여부를 결정 (Flaw #2 수정)
                detail = self._describe_exception(e)
                raise RateLimitError(
                    f"Gemini API Rate Limit 초과 (429): {detail}"
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
            target_comments = sanitize_sensitive_target_comments(
                target_comments,
                topic=topic,
            )
            title = naturalness.ensure_question_punctuation(title)
            content = naturalness.ensure_question_punctuation_in_lines(content)
            for _tc in target_comments:
                if isinstance(_tc, dict):
                    _tc["comment"] = naturalness.ensure_question_punctuation_in_lines(
                        _tc.get("comment", "")
                    )

        except Exception as _exc:
            _api_logger.error(
                "generate_post PARSE ERROR ▶ %s\nRAW (len=%d):\n%s",
                _exc, len(raw_text), raw_text,
            )
            return {"title": "", "content": "", "target_comments": [], "_parse_error": True, "_raw_response": raw_text}

        _sensitive_hits = sensitive_generation_violations(
            f"{title}\n{content}",
            topic=topic,
        )
        if _sensitive_hits:
            _api_logger.warning(
                "generate_post SENSITIVE_GUARD ▶ violations=%s title=%r content=%r topic=%r",
                _sensitive_hits, title, content, topic,
            )
            return {
                "title": "",
                "content": "",
                "target_comments": [],
                "_parse_error": True,
                "_raw_response": raw_text,
                "_safety_error": True,
                "_safety_reasons": _sensitive_hits,
                # 발행에는 사용하지 않되 비공개 검토 자료에는 남긴다.
                "_rejected_title": title,
                "_rejected_content": content,
                "_rejected_comments": target_comments,
            }

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
            "_thought_process": _json_out.get("_thought_process", {}),
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
        titles, title_noise_stats = filter_noise_strings(titles)
        comments, comment_noise_stats = filter_noise_strings(comments)
        style_profile = gallery_style.build_style_profile(
            raw_data,
            gallery_id=str(raw_data.get("gallery_id", "") or ""),
            titles=titles,
            comments=comments,
        )
        upstream_noise_stats = raw_data.get("noise_filter", {}) or {}

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
        top_keywords = sanitize_analysis_keywords(
            top_keywords,
            source_text=all_text,
        )[:top_k]

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
            gallery_identity_context=gallery_purpose.analysis_context(gallery_id),
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
                    "description": "현재 글과 댓글에서 반복적으로 보이는 소재 2~4개",
                },
                "sentiment": {
                    "type": "string",
                    "description": "전반적인 갤러리 감성. 불만/냉소/혼란/기대/무관심/장난/과열 중 가까운 단어",
                },
                "memes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "반복되는 표현, 짧은 드립, 질문 패턴",
                },
                "summary": {
                    "type": "string",
                    "description": "[A: 메인 떡밥] / [B: 서브 떡밥] / [C: 파생 각도] 형식의 짧은 소재 팔레트",
                },
                "ai_analysis": {
                    "type": "string",
                    "minLength": 180,
                    "maxLength": 520,
                    "description": "사람이 읽는 220~340자 브리핑. 소재, 갈등 축, 반응 톤만 포함하고 작문 지시는 넣지 않는다.",
                },
                "generation_guidance": {
                    "type": "string",
                    "minLength": 80,
                    "maxLength": 420,
                    "description": "후속 초안 생성 모델에게 전달할 별도 작문 지시. 금지사항과 안전한 접근 각도를 포함한다.",
                },
            },
            "required": ["hot_topics", "sentiment", "memes", "summary", "ai_analysis", "generation_guidance"],
        }
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_TREND_SCHEMA,
            max_output_tokens=4096,                              # 분석 JSON에는 8k가 과해 TPM/RPM 압력을 키움
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

            response = self._generate_content_paced(
                label="analyze_trend",
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
                "generation_guidance": "파싱 실패 상태에서는 자동 초안 생성을 진행하지 말고 원본 로그를 먼저 확인하세요.",
                "_parse_error":  True,
                "_raw_response": raw_text,
            }
        except Exception as e:
            if self._is_rate_limit_error(e):
                detail = self._describe_exception(e)
                raise RateLimitError(
                    f"Gemini API Rate Limit 초과 (429): {detail}"
                ) from e
            raise

        # ── 민감 주제 라벨 정리 ─────────────────────────────────────────
        # UI와 후속 작문 프롬프트에 원문 비하어/직접 집단명이 재주입되지 않도록
        # LLM 요약 라벨도 추상화된 표현만 남긴다.
        _sensitive_source = "\n".join([
            all_text,
            str(result.get("ai_analysis", "")),
            str(result.get("generation_guidance", "")),
            str(result.get("summary", "")),
        ])
        result["ai_analysis"] = sanitize_user_drama_text(
            str(result.get("ai_analysis", "")),
            source_text=_sensitive_source,
        )
        result["generation_guidance"] = sanitize_user_drama_text(
            str(result.get("generation_guidance", "")),
            source_text=_sensitive_source,
        )
        result["summary"] = sanitize_user_drama_text(
            str(result.get("summary", "")),
            source_text=_sensitive_source,
        )
        result["hot_topics"] = sanitize_analysis_keywords(
            result.get("hot_topics", []),
            source_text=_sensitive_source,
        )
        result["memes"] = sanitize_analysis_keywords(
            result.get("memes", []),
            source_text=_sensitive_source,
        )

        # Current scrape data describes the moment. The ID-derived profile
        # preserves the board's durable subject across rehearsal cycles.
        identity = gallery_purpose.identity_metadata(gallery_id)
        if identity:
            prefix = gallery_purpose.briefing_prefix(gallery_id)
            analysis_text = gallery_purpose.strip_identity_echo(
                str(result.get("ai_analysis") or "").strip(),
                gallery_id,
            )
            if prefix and not analysis_text.startswith(prefix):
                result["ai_analysis"] = f"{prefix} {analysis_text}".strip()
            instruction = gallery_purpose.generation_instruction(gallery_id)
            guidance_text = str(result.get("generation_guidance") or "").strip()
            topic_label = str(identity.get("topic_label") or "").strip()
            has_identity_guidance = (
                bool(topic_label and topic_label in guidance_text)
                and any(marker in guidance_text for marker in ("상시", "기본 분야", "10%"))
            )
            if instruction and instruction not in guidance_text and not has_identity_guidance:
                result["generation_guidance"] = (
                    f"{guidance_text}\n\n{instruction}".strip()
                )
            result["gallery_identity"] = identity

        # ── 7. 공통 메타데이터 주입 ─────────────────────────
        result["top_keywords"] = top_keywords
        # keyword_counts: Plotly 빈도 차트용 (word → 실제 등장 횟수)
        result["keyword_counts"] = {word: counter[word] for word in top_keywords}
        result["author_stats"] = author_stats   # author dominance 요약 문자열
        result["ai_share"]     = ai_share       # ledger 기반 봇 점유율 문자열
        result["style_profile"] = style_profile
        result["stats"] = {
            "titles_count":    len(titles),
            "comments_count":  len(comments),
            "authors_count":   len(authors),
            "keywords_found":  len(filtered),
            "ai_post_count":   _ai_post_count,
            "total_post_count": _total_post_count,
            "noise_post_count": int(upstream_noise_stats.get("post_count", 0) or 0),
            "noise_comment_count": int(upstream_noise_stats.get("comment_count", 0) or 0)
                + int(comment_noise_stats.get("removed_count", 0) or 0),
            "noise_title_count": int(title_noise_stats.get("removed_count", 0) or 0),
        }
        result["noise_filter"] = {
            **upstream_noise_stats,
            "title_samples": title_noise_stats.get("removed_samples", []),
            "comment_samples": comment_noise_stats.get("removed_samples", []),
        }
        # 원본 게시글 목록 pass-through (UI 디버깅용, analyze_trend에서 가공 안 함)
        result["raw_posts"] = raw_data.get("raw_posts", [])

        return result

    # ══════════════════════════════════════════════
    # LLM Judge — 생성된 게시글 품질 판정 (Flash, 저비용)
    # ══════════════════════════════════════════════

    def judge_post(
        self,
        title: str,
        content: str,
        *,
        banned_topics: list[str] | None = None,
        batch_titles: list[str] | None = None,
        gallery_id: str = "",
        topic: str = "",
    ) -> dict:
        """생성된 게시글 1건의 품질을 LLM으로 판정.

        Returns:
            {"pass": True/False, "reason": "...", "fixed_title": "..." or None}
            - pass=False 시 reason에 거부 사유
            - fixed_title: 사소한 결함(물음표 누락 등)은 수정 제안
        """
        _banned_str = ", ".join(banned_topics) if banned_topics else "없음"
        _batch_str = "\n".join(f"  - {t}" for t in (batch_titles or []))
        if not _batch_str:
            _batch_str = "(첫 번째 글)"
        _topic_str = topic[:3000] if topic else "(브리핑 없음)"

        prompt = f"""[Task] 아래 게시글의 품질을 판정해라. JSON으로 응답.

[게시글]
제목: {title}
본문: {content}

[현재 브리핑/작문 지시]
{_topic_str}

[금지 화제 목록] {_banned_str}
[이번 배치 기존 제목]
{_batch_str}

[판정 기준 — 하나라도 위반 시 pass: false]
1. 금지 화제의 동의어·변형·우회 표현이 제목이나 본문에 있는가? (예: "사랑아 시끄럽다" 금지 시 "사랑이 좀 조용히 해라"도 위반)
2. 순수 메타 평론인가? (글 수, 리젠 속도, 분위기 평가만 있고 구체 소재 반응이 없음)
3. 배치 내 기존 제목과 의미적으로 동일한 글인가? (단어만 바꾼 near-duplicate)
4. 제목이 중간에 잘려서 문장이 완성되지 않았는가?
5. 브리핑에 없는 외부 사이트·스포츠·게임·정치 소재를 '{gallery_id}' 이름만 보고 억지로 끌고 왔는가?
6. 현재 브리핑/씨앗 떡밥/주요 소재/반복 표현에 직접 없는 최근 글의 사이트명·개인명·별명을 제목/본문 주제로 끌고 왔는가?
7. 자연스러움 정책을 위반하는가?
{naturalness.judge_policy_text()}

[허용]
- 게시판 ID가 baseball_new13이어도 브리핑에 야구가 없으면 야구 연결을 요구하지 않는다.
- 브리핑의 주요 소재나 반복 표현에 직접 등장한 별명·호칭은 그 소재를 가리키는 커뮤니티 어휘로 본다. 성희롱/비하/저격이 아니라면 "최근 글 별명" 사유로 거부하지 않는다.
- 배치 내 기존 제목과 같은 큰 소재여도 관점, 질문, 감정, 결론이 다르면 통과다. 완전히 같은 주장과 제목 구조일 때만 near-duplicate로 본다.

[출력 형식 — 이것만 출력]
{{"pass": true}} 또는 {{"pass": false, "reason": "위반 사유 1줄"}}
제목이 잘렸거나 물음표가 빠진 경우: {{"pass": true, "fixed_title": "수정된 제목"}}"""

        cfg = types.GenerateContentConfig(
            safety_settings=SAFETY_SETTINGS,
            max_output_tokens=256,
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )

        try:
            response = self._generate_content_paced(
                label="judge_post",
                model=MODEL_NAME,
                contents=prompt,
                config=cfg,
            )
            raw = response.text.strip()
            _api_logger.debug("judge_post RESPONSE ▶ %s", raw)
            result = _parse_json_robust(raw)
            if not isinstance(result, dict):
                return {"pass": True}
            return result
        except Exception as e:
            _api_logger.warning("judge_post FAILED: %s — 기본 통과 처리", e)
            # Judge 실패 시 기본 통과 (생성 자체를 막지 않음)
            return {"pass": True}
