"""Ghost Protocol v5.0 — local Ollama-powered post generation.

Pipeline:
  local Ollama (Qwen) → provider-neutral LLM contract
  DB (winner posts)     → Few-shot examples (content ≤ 300 chars)
  DB (recent posts)     → Context injection ("gallery mood")
                              ↓
  Qwen → structured JSON output {title, content, target_comments}

Model: qwen2.5:3b (GTX 1660 SUPER 기본값; 환경변수로 변경 가능)
Output: Ollama JSON mode + robust JSON parsing
"""

import json
import logging
import os
import random
import re
from collections import Counter
from pathlib import Path
from typing import Optional

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
from .application import intel_result, llm_throttle, llm_usage, trend_cache
from .application.draft_quality import grounded_fallback, review_draft
from .application.draft_pipeline import (
    DraftCard,
    build_draft_card,
    build_source_brief,
)
from .application.llm_provider import LLMProvider, LLMRequest
from .application.ollama_client import OllamaClient
from .application.prompt_compiler import compile_post_prompt
from .domain import gallery_purpose, gallery_style, naturalness, writing_enrichment

# .env 에서 로컬 Ollama 설정 로딩
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
    """LLM 응답 텍스트에서 JSON 오브젝트를 안전하게 추출한다.

    처리 순서:
      1. 마크다운 코드펜스(```json ... ```) 내부 추출 시도
      2. 펜스가 없으면 raw 텍스트에서 첫 번째 { ... } 블록 추출
      3. json.loads() 로 파싱 — 실패 시 JSONDecodeError를 그대로 전파

    이 방식은 아래 모든 케이스를 커버한다:
      · ```json\\n{...}\\n```   (표준 마크다운)
      · ```\\n{...}\\n```       (언어 태그 없음)
      · {... }                  (펜스 없음)
      · 앞뒤 산문 + { ... }    (모델이 설명을 붙인 경우)
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
# 로컬 모델 기본값. 설치된 모델과 운영 목적에 맞게 .env에서 변경할 수 있다.
# ══════════════════════════════════════════════
MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5:3b").strip() or "qwen2.5:3b"
FALLBACK_MODEL_NAMES = tuple(
    model
    for model in (
        item.strip()
        for item in os.getenv(
            "OLLAMA_FALLBACK_MODELS",
            "qwen2.5:7b",
        ).split(",")
    )
    if model and model != MODEL_NAME
)


class RateLimitError(Exception):
    """Provider가 일시적으로 요청을 처리하지 못했을 때의 호환 예외."""


def _shorten_log_value(value: object, *, limit: int = 800) -> str:
    """Return a compact, single-line representation for API diagnostics."""

    try:
        text = str(value)
    except Exception:
        text = repr(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _env_float(name: str, default: float, *, lower: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, value)


def _env_int(name: str, default: int, *, lower: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, value)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _model_prefers_full_prompt(model_name: str) -> bool:
    """Return whether a model has enough capacity for the quality-first path."""

    value = str(model_name or "").strip().lower()
    return any(marker in value for marker in (":7b", ":8b", ":9b", ":14b", ":32b"))

# ══════════════════════════════════════════════
# System prompt → prompts/system_base.txt
# pm.load("system_base.txt") 로 동적 주입
# ══════════════════════════════════════════════

# content 최대 길이 (토큰 절약)
MAX_CONTENT_LENGTH = 300

# ── 댓글 길이 룰 — Phase 9: 동적 랜덤 할당 ────────────────────────────────
# Legacy fallback only.  The active path now uses writing_enrichment.comment_length_rule()
# so long comments appear only when the collected source rhythm supports them.
_COMMENT_LENGTH_RULES: list[str] = [
    "1줄. 짧게 반응만 둔다.",
    "2줄. 첫 줄 반응, 둘째 줄 아주 짧은 이유.",
    "3줄 이내. 타겟 글에 이미 긴 댓글 흐름이 있을 때만 허용한다.",
]


class GhostBrain:
    """DC Inside 스타일 게시글 생성기 -- local Ollama provider 기반."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        model_name: str | None = None,
    ):
        self.model_name = (model_name or MODEL_NAME).strip() or MODEL_NAME
        self.fallback_model_names = tuple(
            model for model in FALLBACK_MODEL_NAMES if model != self.model_name
        )
        self.provider: LLMProvider = provider or OllamaClient(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            model=self.model_name,
            timeout_seconds=_env_float("OLLAMA_TIMEOUT_SEC", 120.0, lower=1.0),
            # The full writing prompt is retained for 7B-class models.  An
            # explicit OLLAMA_NUM_CTX still wins, so small-GPU users can cap it.
            num_ctx=_env_int(
                "OLLAMA_NUM_CTX",
                8192 if _model_prefers_full_prompt(self.model_name) else 4096,
            ),
            keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip() or "10m",
        )
        self._provider = self.provider

    # ══════════════════════════════════════════════
    # 내부 헬퍼
    # ══════════════════════════════════════════════

    def _get_gallery_context(self, gallery_id: str) -> str:
        """갤러리 ID → legacy 고유 문법 룰 + 퓨샷 예시 프롬프트 블록 반환.

        라우팅 우선순위:
          1. gallery_contexts.json에서 gallery_id 정확 매치
          2. 포함 관계 매치 (key in gallery_id OR gallery_id in key)
          3. "default" 폴백

        새 갤러리는 여기에 ID별 하드코딩을 추가하지 않는다. 지속 분야는
        gallery_purposes.json의 ID/name 토큰 추론과 현재 원본 문체 프로필로
        처리한다.

        토큰 최적화:
          - 문법 룰 최대 3개, 퓨샷 최대 2개, 본문 80자 제한
          - 빈 컨텍스트(default fewshot=[])는 룰만 반환 → ~150 토큰 이하
        """
        ctx_db: dict = pm.load_json("gallery_contexts.json")
        if not isinstance(ctx_db, dict):
            return ""
        gallery_id = str(gallery_id or "").strip()

        # 1차: 정확 매치
        ctx = ctx_db.get(gallery_id) if gallery_id else None

        # 2차: 부분 포함 매치 (_로 시작하는 메타 키 제외)
        if ctx is None:
            for key, val in ctx_db.items():
                key_text = str(key)
                if key_text.startswith("_") or key_text == "default" or not gallery_id:
                    continue
                if key_text in gallery_id or gallery_id in key_text:
                    ctx = val
                    break

        # Registered purpose domains already receive their durable identity
        # from gallery_purpose.py.  Do not inject the generic/default few-shot
        # here: for universe that default block contains shopping/game wording
        # and can pull a 7B writer off-topic.
        if ctx is None and gallery_purpose.get_profile(gallery_id):
            return ""

        # 3차: default 폴백 for genuinely unknown galleries
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
        """Extract useful provider error details without crashing logging."""

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

    def _generate_content_paced(
        self,
        *,
        label: str,
        prompt: str | None = None,
        contents: str | None = None,
        system: str = "",
        json_schema: dict | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        **_legacy_kwargs,
    ):
        """Send one request through the provider-neutral local LLM contract.

        ``contents`` remains accepted as a short-lived compatibility alias so
        test doubles and older callers can migrate without changing behavior.
        No remote fallback is attempted: the worker must remain local.
        """
        request_prompt = prompt if prompt is not None else (contents or "")
        request = LLMRequest(
            task=label,
            system=system,
            prompt=request_prompt,
            json_schema=json_schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        waited = llm_throttle.wait_before_call(label)
        if waited:
            _api_logger.debug("llm throttle wait %.2fs before %s", waited, label)
        call_record = llm_usage.begin_call(
            label=label,
            model=self.model_name,
            contents=request_prompt,
        )
        try:
            response = self.provider.generate(request)
        except Exception as err:
            llm_usage.record_error(call_record, err)
            if self._is_rate_limit_error(err):
                llm_throttle.note_rate_limit_pause(5.0)
            _api_logger.warning(
                "ollama request failed label=%s model=%s detail=%s",
                label,
                self.model_name,
                self._describe_exception(err),
            )
            raise
        llm_usage.record_success(call_record, response)
        _api_logger.debug(
            "ollama response label=%s model=%s usage=%s",
            label,
            getattr(response, "model", self.model_name),
            getattr(response, "usage", {}),
        )
        return response

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
            response = self._generate_content_paced(
                label="suggest_topic",
                prompt=prompt,
                system=pm.render("system_base.txt", gallery_id=gallery_id),
                json_schema={
                    "type": "object",
                    "properties": {"topic": {"type": "string"}},
                    "required": ["topic"],
                },
                temperature=0.9,
                max_output_tokens=200,
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
        composition_profile: Optional[dict] = None,
        expected_slot: str = "",
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
            expected_slot: 앱이 선택한 소재 슬롯. 모델이 생성하지 않고
                           결과 메타데이터에 앱이 주입한다.

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
        source_composition_profile = (
            composition_profile
            if isinstance(composition_profile, dict)
            else writing_enrichment.build_composition_profile(
                {"raw_posts": recent_posts or []},
                recent_posts=recent_posts,
            )
        )
        base_composition_profile_block = (
            ""
            if "[Composition Profile]" in str(topic or "")
            else writing_enrichment.prompt_block(source_composition_profile)
        )
        generation_variation_block = writing_enrichment.generation_variation_block(
            source_composition_profile,
            requested_length=length,
            rng=random,
        )
        composition_profile_block = "\n\n".join(
            block
            for block in (base_composition_profile_block, generation_variation_block)
            if block
        )
        base_comment_enrichment_block = (
            ""
            if "[Comment Composition Profile]" in str(topic or "")
            else writing_enrichment.comment_prompt_block(source_composition_profile)
        )
        comment_variation_block = writing_enrichment.comment_variation_block(
            source_composition_profile,
            rng=random,
        )
        comment_enrichment_block = "\n\n".join(
            block
            for block in (base_comment_enrichment_block, comment_variation_block)
            if block
        )
        shared_writing_contract = pm.render("shared_writing_contract.txt")

        if recent_posts:
            # Phase 9: 댓글 길이 룰 랜덤 선택 — 봇마다 대사 길이 변주
            _comment_length_rule = writing_enrichment.comment_length_rule(
                source_composition_profile,
                rng=random,
            )
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
                comment_enrichment_block=comment_enrichment_block,
                shared_writing_contract=shared_writing_contract,
            )
        else:
            recent_posts_context = ""

        # ── 갤러리 고유 언어 컨텍스트 — Dynamic Routing ──────────────────────
        # gallery_contexts.json에서 gallery_id로 조회한 문법 룰 + 퓨샷 블록.
        # 레거시 경로에서만 마스터 프롬프트 앞에 붙인다. 구조화 경로는
        # 소스 브리프와 Draft Card에 필요한 사실만 다시 압축한다.
        _gal_ctx = self._get_gallery_context(gallery_id)
        if _gal_ctx:
            parts.append(_gal_ctx)

        # ── 최종 작성 터널 선택 ─────────────────────────────────────────────
        # 기본은 구조화 카드다. 긴 원본 프롬프트를 그대로 쓰는 경로는
        # 진단·비교용으로만 LLM_DRAFT_PIPELINE_MODE=legacy로 보존한다.
        _pipeline_mode = os.getenv("LLM_DRAFT_PIPELINE_MODE", "structured").strip().lower()
        _draft_card: DraftCard | None = None
        if _pipeline_mode in {"structured", "card"}:
            _source_brief = build_source_brief(topic, gallery_id, expected_slot)
            _draft_card = build_draft_card(
                _source_brief,
                tone=tone,
                length=length,
                # The profile is carried in dedicated card fields below. Do
                # not duplicate the legacy `[페르소나 심화]` prose inside the
                # structured writer prompt where it can be copied verbatim.
                tone_description=str(tone_desc.get(tone, tone_desc["cynical"])),
                persona_profile=_prof if isinstance(_prof, dict) else {},
                has_comment_targets=bool(recent_posts),
            )
            prompt = _draft_card.writer_prompt()
            _pipeline_mode = "structured_card"
        else:
            # ── 레거시 작문 지시 — prompts/generate_post.txt에서 로드 ───────
            # 하드코딩 제로: 분량·톤·키워드·교차지시를 템플릿 변수로 주입.
            rendered_master_prompt = pm.render(
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
                composition_profile_block=composition_profile_block,
                comment_enrichment_block=comment_enrichment_block,
                shared_writing_contract=shared_writing_contract,
            )
            _prompt_mode = os.getenv("LLM_PROMPT_MODE", "auto").strip().lower()
            if _prompt_mode == "auto":
                _prompt_mode = "full" if _model_prefers_full_prompt(self.model_name) else "focused"
            compiled_master_prompt = compile_post_prompt(
                rendered_master_prompt,
                include_comments=bool(recent_posts),
                slot=expected_slot,
                mode=_prompt_mode,
            )
            prompt = "\n\n---\n\n".join([*parts, compiled_master_prompt])

        # ── Ollama JSON 호출 ──
        # 모델은 게시글 필드만 생성한다. 슬롯·페르소나·QC 메타데이터는
        # 호출자가 결정해 모델이 내부 지시를 본문으로 복사하지 않게 한다.
        _POST_SCHEMA = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                # Keep the grammar small enough for a 6GB GPU.  The application
                # parser performs the detailed post_no/comment validation.
                "target_comments": {"type": "array"},
            },
            "required": ["title", "content", "target_comments"],
        }
        # Ollama's detailed grammar can consume most of a 4K context on
        # Korean 7B runs.  Keep native JSON mode as the default and retain the
        # detailed schema as an explicit opt-in; the application parser still
        # validates every returned field and target comment.
        _post_schema = _POST_SCHEMA if _env_bool("LLM_JSON_SCHEMA_MODE") else None
        try:
            response = self._generate_content_paced(
                label="generate_post",
                prompt=prompt,
                system=pm.render("system_base.txt", gallery_id=gallery_id),
                json_schema=_post_schema,
                max_output_tokens=2048 if _env_bool("LLM_COST_SAVER_MODE") else 3072,
                # Lower variance keeps a local 7B model anchored to the
                # supplied source while persona variation comes from the
                # selected profile and wave plan.
                temperature=_env_float("LLM_GENERATION_TEMPERATURE", 0.4, lower=0.1),
            )
        except Exception as e:
            if self._is_rate_limit_error(e):
                detail = self._describe_exception(e)
                raise RateLimitError(
                    f"로컬 Ollama 요청 제한 또는 일시 오류: {detail}"
                ) from e
            raise  # 다른 에러는 그대로 상위로 전파

        # ── Debug: 중단 원인 로깅 ──
        try:
            finish_reason = (getattr(response, "raw", {}) or {}).get("done_reason", "UNKNOWN")
            _api_logger.debug("generate_post DONE REASON ▶ %s", finish_reason)
        except Exception:
            pass

        # ── JSON 전용 파서 (Native JSON Mode 강제 적용) ──────────────────────
        # Ollama JSON mode 적용으로 마크다운 펜스를 억제한다.
        # 파싱 실패 = 구조적 이상 (빈 응답, 검열 등) → _parse_error Abort 신호 반환.
        # "무제" + 원본 텍스트 포스팅 버그 완전 제거.
        raw_text = response.text.strip()

        # ── 로그: Raw 응답 + finish_reason 기록 ──────────────────────────────
        _finish_reason = str((getattr(response, "raw", {}) or {}).get("done_reason", "UNKNOWN"))
        _api_logger.debug(
            "generate_post RESPONSE ▶ len=%d finish_reason=%s\n%s\n%s",
            len(raw_text), _finish_reason, "─" * 60, raw_text,
        )
        if _finish_reason not in {"UNKNOWN", "stop", "STOP", "FinishReason.STOP"}:
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

        if _draft_card is not None:
            return self._finalize_structured_post(
                card=_draft_card,
                recent_posts=recent_posts,
                expected_slot=expected_slot,
                title=title,
                content=content,
                target_comments=target_comments,
                raw_text=raw_text,
            )

        _thought_process = {
            "slot_used": str(expected_slot or "").strip().upper(),
        }
        if _draft_card is not None:
            _thought_process.update(
                {
                    "pipeline": "structured_card",
                    "focus": _draft_card.brief.focus,
                    "anchors": list(_draft_card.brief.anchors),
                }
            )
        return {
            "title":           title,
            "content":         content,
            "target_comments": target_comments,
            "_thought_process": _thought_process,
        }

    def _quality_failure_result(
        self,
        *,
        raw_text: str,
        issues: tuple[str, ...] | list[str],
        title: str = "",
        content: str = "",
        target_comments: object = None,
    ) -> dict:
        """Return a non-postable result for a failed quality contract."""

        return {
            "title": "",
            "content": "",
            "target_comments": [],
            "_parse_error": True,
            "_quality_error": True,
            "_quality_issues": list(dict.fromkeys(str(item) for item in issues)),
            "_raw_response": raw_text,
            "_rejected_title": title,
            "_rejected_content": content,
            "_rejected_comments": list(target_comments or [])
            if isinstance(target_comments, list)
            else [],
        }

    def _review_post_locally(
        self,
        *,
        card: DraftCard,
        title: str,
        content: str,
        target_comments: list[dict],
    ) -> tuple[bool, tuple[str, ...]]:
        """Ask the same local model for a narrow, fail-closed quality verdict."""

        prompt = "\n".join(
            (
                "[품질 검수]",
                "초안이 아래 작문 카드의 사실·페르소나·문장 계약을 모두 지키는지 판정한다.",
                "입력에 없는 수치·거리·원인·연구·발표·개인 경험, 내부 지시 누출, 불완전 문장, 페르소나 동작 불일치가 하나라도 있으면 pass=false다.",
                f"- 제목: {title}",
                f"- 본문: {content}",
                f"- 댓글: {json.dumps(target_comments, ensure_ascii=False)}",
                card.writer_prompt(),
                '출력은 JSON 하나만: {"pass":true,"issues":[]} 또는 {"pass":false,"issues":["issue_code"]}',
            )
        ).strip()
        try:
            response = self._generate_content_paced(
                label="review_post",
                prompt=prompt,
                system=(
                    "너는 로컬 원고 품질 검사기다. 작문하지 말고 pass와 issue 코드만 JSON으로 반환한다. "
                    "근거가 부족하면 통과시키지 않는다."
                ),
                json_schema={
                    "type": "object",
                    "properties": {
                        "pass": {"type": "boolean"},
                        "issues": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["pass", "issues"],
                },
                temperature=0.0,
                max_output_tokens=256,
            )
            data = _parse_json_robust(str(getattr(response, "text", "") or ""))
            passed = data.get("pass")
            raw_issues = data.get("issues")
            if not isinstance(passed, bool) or not isinstance(raw_issues, list):
                raise ValueError("critic contract is incomplete")
            issues = tuple(
                str(item).strip()
                for item in raw_issues
                if str(item).strip()
            )
            if not passed and not issues:
                issues = ("critic_unspecified",)
            if passed and issues:
                return False, tuple(dict.fromkeys((*issues, "critic_conflict")))
            return passed, issues
        except Exception as exc:
            _api_logger.warning("review_post FAILED ▶ %s", _shorten_log_value(exc))
            return False, ("critic_error",)

    def _repair_post_locally(
        self,
        *,
        card: DraftCard,
        title: str,
        content: str,
        target_comments: list[dict],
        issues: tuple[str, ...],
    ) -> dict:
        """Repair one rejected candidate without widening its source contract."""

        comment_rule = (
            "기존에 허용된 타겟 post_no만 유지하고 새 post_no를 만들지 않는다."
            if card.has_comment_targets
            else "target_comments는 반드시 빈 배열([])이다."
        )
        prompt = "\n".join(
            (
                "[수정 터널]",
                f"검수 오류 코드: {', '.join(issues)}",
                f"이전 제목: {title}",
                f"이전 본문: {content}",
                "확인된 사실·구체 앵커·선택 페르소나의 말투와 행동은 유지한다.",
                "입력 밖 수치·거리·선명도·원인·변화·비교·사건·연구·발표·개인 경험은 삭제한다.",
                "제목은 판단을 끝내고, 본문은 자연스러운 완결 문장으로 닫는다.",
                "내부 지시·페르소나 설명·검수 코드·메타 발언은 출력하지 않는다.",
                comment_rule,
                card.writer_prompt(),
            )
        ).strip()
        try:
            response = self._generate_content_paced(
                label="repair_post",
                prompt=prompt,
                system=(
                    "너는 이전 초안의 오류만 고치는 로컬 한국어 원고 편집기다. "
                    "새 사실을 추가하지 말고 JSON 객체 하나만 반환한다."
                ),
                json_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "target_comments": {"type": "array"},
                    },
                    "required": ["title", "content", "target_comments"],
                },
                temperature=0.15,
                max_output_tokens=512,
            )
            raw_text = str(getattr(response, "text", "") or "").strip()
            data = _parse_json_robust(raw_text)
            repaired_title = naturalness.ensure_question_punctuation(
                str(data.get("title") or "").strip()
            )
            repaired_content = naturalness.ensure_question_punctuation_in_lines(
                str(data.get("content") or "").strip()
            )
            if not repaired_title or not repaired_content:
                return self._quality_failure_result(
                    raw_text=raw_text,
                    issues=("repair_empty_field",),
                    title=title,
                    content=content,
                    target_comments=target_comments,
                )
            allowed_ids = {
                str(item.get("post_no") or "").strip()
                for item in target_comments
                if isinstance(item, dict)
            }
            repaired_comments: list[dict] = []
            raw_comments = data.get("target_comments", [])
            if card.has_comment_targets and isinstance(raw_comments, list):
                for item in raw_comments:
                    if not isinstance(item, dict):
                        continue
                    post_no = str(item.get("post_no") or "").strip()
                    comment = str(item.get("comment") or "").strip()
                    if post_no in allowed_ids and comment:
                        repaired_comments.append(
                            {
                                "post_no": post_no,
                                "comment": naturalness.ensure_question_punctuation_in_lines(comment),
                            }
                        )
            sensitive_hits = sensitive_generation_violations(
                f"{repaired_title}\n{repaired_content}",
                topic=str(card.brief.focus),
            )
            if sensitive_hits:
                return self._quality_failure_result(
                    raw_text=raw_text,
                    issues=("repair_sensitive_content",),
                    title=repaired_title,
                    content=repaired_content,
                    target_comments=repaired_comments,
                )
            return {
                "title": repaired_title,
                "content": repaired_content,
                "target_comments": repaired_comments,
                "_raw_response": raw_text,
            }
        except Exception as exc:
            _api_logger.warning("repair_post FAILED ▶ %s", _shorten_log_value(exc))
            return self._quality_failure_result(
                raw_text=_shorten_log_value(exc),
                issues=("repair_error",),
                title=title,
                content=content,
                target_comments=target_comments,
            )

    def _grounded_fallback_post(
        self,
        *,
        card: DraftCard,
        expected_slot: str,
        raw_text: str,
        issues: tuple[str, ...],
    ) -> dict:
        """Return a deterministic fact-only sentence after model repair fails."""

        fallback_title, fallback_content = grounded_fallback(card)
        fallback_review = review_draft(card, fallback_title, fallback_content, [])
        if not fallback_review.accepted:
            return self._quality_failure_result(
                raw_text=raw_text,
                issues=tuple(dict.fromkeys((*issues, *fallback_review.issues))),
                title=fallback_title,
                content=fallback_content,
            )
        return {
            "title": fallback_title,
            "content": fallback_content,
            "target_comments": [],
            "_thought_process": {
                "slot_used": str(expected_slot or "").strip().upper(),
                "pipeline": "structured_card_fallback",
                "quality_mode": "strict",
                "quality_issues": list(issues),
                "fallback": True,
                "focus": card.brief.focus,
                "anchors": list(card.brief.anchors),
            },
        }

    def _finalize_structured_post(
        self,
        *,
        card: DraftCard,
        recent_posts: Optional[list[dict]],
        expected_slot: str,
        title: str,
        content: str,
        target_comments: list[dict],
        raw_text: str,
    ) -> dict:
        """Run deterministic review, local critic, and one bounded repair."""

        mode = os.getenv("LLM_DRAFT_QC_MODE", "strict").strip().lower()
        if mode not in {"strict", "deterministic", "off"}:
            mode = "strict"
        review = review_draft(
            card,
            title,
            content,
            target_comments,
            recent_posts=recent_posts,
        )
        if mode == "off":
            review = review_draft(
                card,
                title,
                content,
                target_comments,
                recent_posts=recent_posts,
            )
            if not review.accepted:
                return self._quality_failure_result(
                    raw_text=raw_text,
                    issues=review.issues,
                    title=title,
                    content=content,
                    target_comments=target_comments,
                )
            mode = "off"
            critic_issues: tuple[str, ...] = ()
        else:
            critic_issues = ()
            if review.accepted and mode == "strict":
                critic_ok, critic_issues = self._review_post_locally(
                    card=card,
                    title=title,
                    content=content,
                    target_comments=target_comments,
                )
                if not critic_ok and critic_issues == ("critic_error",):
                    return self._quality_failure_result(
                        raw_text=raw_text,
                        issues=critic_issues,
                        title=title,
                        content=content,
                        target_comments=target_comments,
                    )
            if (not review.accepted) or critic_issues:
                repair_issues = tuple(dict.fromkeys((*review.issues, *critic_issues)))
                repaired = self._repair_post_locally(
                    card=card,
                    title=title,
                    content=content,
                    target_comments=target_comments,
                    issues=repair_issues,
                )
                if repaired.get("_parse_error"):
                    return self._grounded_fallback_post(
                        card=card,
                        expected_slot=expected_slot,
                        raw_text=str(repaired.get("_raw_response") or raw_text),
                        issues=repair_issues,
                    )
                title = str(repaired.get("title") or "").strip()
                content = str(repaired.get("content") or "").strip()
                target_comments = list(repaired.get("target_comments") or [])
                review = review_draft(
                    card,
                    title,
                    content,
                    target_comments,
                    recent_posts=recent_posts,
                )
                if not review.accepted:
                    return self._grounded_fallback_post(
                        card=card,
                        expected_slot=expected_slot,
                        raw_text=str(repaired.get("_raw_response") or raw_text),
                        issues=tuple(dict.fromkeys((*repair_issues, *review.issues))),
                    )
                if mode == "strict":
                    critic_ok, critic_issues = self._review_post_locally(
                        card=card,
                        title=title,
                        content=content,
                        target_comments=target_comments,
                    )
                    if not critic_ok:
                        return self._grounded_fallback_post(
                            card=card,
                            expected_slot=expected_slot,
                            raw_text=str(repaired.get("_raw_response") or raw_text),
                            issues=critic_issues or ("critic_rejected",),
                        )
                pipeline = "structured_card_repair"
            else:
                pipeline = "structured_card"

        return {
            "title": title,
            "content": content,
            "target_comments": target_comments,
            "_thought_process": {
                "slot_used": str(expected_slot or "").strip().upper(),
                "pipeline": pipeline if mode != "off" else "structured_card",
                "quality_mode": mode,
                "focus": card.brief.focus,
                "anchors": list(card.brief.anchors),
                "quality_issues": list(critic_issues),
            },
        }

    def generate_post_compact(
        self,
        *,
        topic: str,
        gallery_id: str,
        tone: str = "neutral",
        length: str = "짧게 (1~2문장)",
        focus: str = "",
        recent_posts: Optional[list[dict]] = None,
    ) -> dict:
        """Generate one small, purpose-anchored draft after a long retry fails.

        The normal writer prompt intentionally carries many style and safety
        blocks.  On a small local model that large context can cause malformed
        JSON or topic drift.  This recovery path keeps only the durable board
        purpose, one concrete focus, and the output contract; it never posts.
        """

        profile = gallery_purpose.get_profile(gallery_id)
        topic_label = str(profile.get("topic_label") or "게시판 소재").strip()
        focus_text = str(focus or "").strip()
        persona_instruction = ""
        persona_profiles = pm.load_json("persona_profiles.json")
        persona_profile = persona_profiles.get(tone) if isinstance(persona_profiles, dict) else None
        if isinstance(persona_profile, dict):
            persona_instruction = (
                f"페르소나 행동: {persona_profile.get('vocab_style', '')}. "
                f"좋은 동작: {' / '.join(persona_profile.get('good_moves', []))}. "
                f"피할 동작: {' / '.join(persona_profile.get('bad_moves', []))}."
            )
        if not focus_text:
            candidates = gallery_purpose.purpose_candidates(
                gallery_id,
                recent_posts or (),
                allow_fallback=True,
            )
            focus_text = candidates[0] if candidates else topic_label
        prompt = (
            "한국어 커뮤니티에 올릴 짧은 초안 1개를 만든다. 반드시 JSON 객체 하나만 출력한다.\n"
            f"게시판 기본 분야: {topic_label}\n"
            f"이번 글의 구체 초점: {focus_text}\n"
            f"말투: {tone}; 분량: {length}\n"
            f"{persona_instruction}\n"
            "초점의 구체 명사나 장면을 제목 또는 본문에 반드시 한 번 넣는다. "
            "사람·닉네임·논란·게임·정치·게시판 메타 평론은 쓰지 않는다. "
            "새 사건을 만들지 말고 관측 가능한 장면 하나만 짧게 쓴다.\n"
            '출력 형식: {"title":"짧은 제목","content":"한두 문장 본문","target_comments":[]} '
            "target_comments는 항상 빈 배열이다."
        )
        response = self._generate_content_paced(
            label="generate_post_compact",
            prompt=prompt,
            system=(
                "너는 짧고 사실적인 한국어 커뮤니티 초안 작성기다. "
                "설명·마크다운·추가 키는 출력하지 않는다."
            ),
            json_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "target_comments": {"type": "array"},
                },
                "required": ["title", "content", "target_comments"],
            },
            temperature=0.25,
            max_output_tokens=384,
        )
        raw_text = str(getattr(response, "text", "") or "").strip()
        try:
            data = _parse_json_robust(raw_text)
            title = naturalness.ensure_question_punctuation(
                str(data.get("title") or "").strip()
            )
            content = naturalness.ensure_question_punctuation_in_lines(
                str(data.get("content") or "").strip()
            )
        except Exception as exc:
            _api_logger.warning("generate_post_compact PARSE ERROR: %s", exc)
            return {
                "title": "",
                "content": "",
                "target_comments": [],
                "_parse_error": True,
                "_raw_response": raw_text,
            }
        if not title or not content:
            return {
                "title": "",
                "content": "",
                "target_comments": [],
                "_parse_error": True,
                "_raw_response": raw_text,
            }
        sensitive_hits = sensitive_generation_violations(
            f"{title}\n{content}",
            topic=topic,
        )
        if sensitive_hits:
            return {
                "title": "",
                "content": "",
                "target_comments": [],
                "_parse_error": True,
                "_safety_error": True,
                "_safety_reasons": sensitive_hits,
                "_rejected_title": title,
                "_rejected_content": content,
                "_raw_response": raw_text,
            }
        return {
            "title": title,
            "content": content,
            "target_comments": [],
            "_thought_process": {
                "slot_used": "G",
                "target_noun": focus_text,
                "start_style": "compact_fallback",
            },
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
            → 키워드 + 샘플만 로컬 Qwen으로 전달 (토큰 최소화)
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
        composition_profile = writing_enrichment.build_composition_profile(
            raw_data,
            style_profile=style_profile,
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
        # 작성자 점유율 Top 5 → "$author_stats" 변수로 로컬 LLM에 전달
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

        # ── 5. 로컬 LLM 전달용 경량 페이로드 조립 ────────────
        # 제목 샘플: 최대 20개
        kw_text     = ", ".join(top_keywords[:20])
        titles_text = "\n".join(f"- {t}" for t in titles[:20])
        # 댓글 샘플: 최대 15개 × 50자 trim
        comments_text = "\n".join(
            f"- {c[:50]}" for c in comments[:15]
        )

        gallery_id = raw_data.get("gallery_id", "알 수 없음")

        # GTX 1660 SUPER에서 운용하는 3B 모델은 긴 안전/문체 지시와
        # 대량 원문을 함께 받으면 출력 형식의 표기를 계속 이어 쓰는 경향이
        # 있다. 분석 전용 경량 계약은 원본 확인과 안전 경계를 유지하면서
        # 입력과 응답을 작게 제한한다. 7B 이상은 기존의 풍부한 분석 지시를
        # 유지하되, 어느 경로에서든 모델은 레이블 없는 topic_slots만 낸다.
        use_compact_contract = _env_bool(
            "LLM_TREND_COMPACT_MODE",
            default=not _model_prefers_full_prompt(
                str(getattr(self, "model_name", MODEL_NAME) or MODEL_NAME)
            ),
        )
        if use_compact_contract:
            prompt_template = pm.load("trend_analysis_compact.txt")
            prompt = pm.render(
                "trend_analysis_compact.txt",
                gallery_id=gallery_id,
                kw_text=", ".join(top_keywords[:12]),
                titles_text="\n".join(f"- {t[:80]}" for t in titles[:12]),
                comments_text="\n".join(f"- {c[:60]}" for c in comments[:8]),
            )
        else:
            prompt_template = pm.load("trend_analysis.txt")
            prompt = pm.render(
                "trend_analysis.txt",
                gallery_id=gallery_id,
                gallery_identity_context=gallery_purpose.analysis_context(gallery_id),
                rehearsal_analysis_notes=str(raw_data.get("rehearsal_analysis_notes") or ""),
                top_k_count=min(len(top_keywords), 20),
                kw_text=kw_text,
                titles_text=titles_text,
                comments_text=comments_text,
                author_stats=author_stats,
                ai_share=ai_share,
            )
        cache_key = trend_cache.build_key(
            gallery_id=str(gallery_id),
            titles=titles,
            comments=comments,
            prompt_template=prompt_template,
            extra=str(raw_data.get("rehearsal_analysis_notes") or ""),
        )

        # ── 6. 로컬 LLM 호출 (분석용 — JSON Mode + Schema 계약) ──
        # response_mime_type: API 레벨 순수 JSON 강제 → 마크다운 펜스 원천 차단
        # response_schema:    반환 구조·타입 고정 → key 누락·임의 구조 변경 불가
        # max_output_tokens:  2048 (hot_topics/summary 잘림 방지)
        _TREND_SCHEMA = {
            "type": "object",
            "properties": {
                "hot_topics": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 72},
                    "minItems": 1,
                    "maxItems": 4,
                    "description": "현재 글과 댓글에서 반복적으로 보이는 소재 2~4개",
                },
                "sentiment": {
                    "type": "string",
                    "maxLength": 24,
                    "description": "전반적인 갤러리 감성. 불만/냉소/혼란/기대/무관심/장난/과열 중 가까운 단어",
                },
                "memes": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 72},
                    "maxItems": 4,
                    "description": "반복되는 표현, 짧은 드립, 질문 패턴",
                },
                "topic_slots": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 48},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "후속 초안 소재가 되는 짧은 명사구 3개. 라벨이나 번호는 넣지 않는다.",
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
            "required": ["hot_topics", "sentiment", "memes", "topic_slots", "ai_analysis", "generation_guidance"],
        }
        raw_text = ""
        cached_result = trend_cache.get(cache_key)
        if cached_result:
            result = cached_result
            result["_cache_hit"] = True
            _api_logger.debug(
                "analyze_trend CACHE HIT ▶ gallery=%s key=%s ttl=%s",
                gallery_id,
                cache_key[:12],
                os.getenv("LLM_TREND_CACHE_TTL_SEC", "900"),
            )
        else:
            try:
                # ── 로그: 로컬 LLM에 보내는 프롬프트 전문 기록 ──────────────────
                _api_logger.debug(
                    "analyze_trend PROMPT ▶ gallery=%s contract=%s\n%s\n%s",
                    gallery_id,
                    "compact" if use_compact_contract else "full",
                    "─" * 60,
                    prompt,
                )

                response = self._generate_content_paced(
                    label="analyze_trend",
                    prompt=prompt,
                    json_schema=_TREND_SCHEMA,
                    max_output_tokens=(
                        768
                        if use_compact_contract
                        else (3072 if _env_bool("LLM_COST_SAVER_MODE") else 4096)
                    ),
                    temperature=0.3,
                )
                raw_text = response.text.strip()

                # ── 로그: Raw 응답 + 완료 사유 기록 ────────────────
                _finish_reason = str((getattr(response, "raw", {}) or {}).get("done_reason", "UNKNOWN"))
                _api_logger.debug(
                    "analyze_trend RESPONSE ▶ len=%d finish_reason=%s\n%s\n%s",
                    len(raw_text), _finish_reason, "─" * 60, raw_text,
                )
                # finish_reason != STOP → 잘림/안전필터 경고 (MAX_TOKENS 포함)
                if _finish_reason not in {"UNKNOWN", "stop", "STOP"}:
                    _api_logger.warning(
                        "analyze_trend NON-STOP finish_reason=%s — 응답 잘림 또는 필터링 가능성",
                        _finish_reason,
                    )
                    raise intel_result.TrendPayloadError(
                        f"analysis response stopped with {_finish_reason}",
                        reason="truncated_response",
                    )

                # 강화된 JSON 파싱 (마크다운 펜스 + 앞뒤 산문 제거)
                result = intel_result.normalize_trend_payload(
                    _parse_json_robust(raw_text)
                )
                trend_cache.set(cache_key, result)

            except (json.JSONDecodeError, intel_result.TrendPayloadError) as _exc:
                # ── 로그: 파싱 실패 상세 기록 ────────────────────────────────
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
                    "_failure_reason": getattr(_exc, "reason", "invalid_json"),
                    "_raw_response": raw_text,
                }
            except Exception as e:
                if self._is_rate_limit_error(e):
                    detail = self._describe_exception(e)
                    raise RateLimitError(
                        f"로컬 Ollama 요청 제한 또는 일시 오류: {detail}"
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
            result["gallery_identity"] = identity
        if identity and not intel_result.is_parse_failed(result):
            analysis_text = gallery_purpose.strip_identity_echo(
                str(result.get("ai_analysis") or "").strip(),
                gallery_id,
            )
            # The inferred subject is durable metadata, not evidence from the
            # current scrape.  Keep it out of the trend briefing so a later
            # draft cannot mistake an ID-derived baseline for a live topic.
            # The separate generation instruction still reserves the small
            # purpose share required by the gallery profile.
            result["ai_analysis"] = analysis_text
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

        # ── 7. 공통 메타데이터 주입 ─────────────────────────
        result["top_keywords"] = top_keywords
        # keyword_counts: Plotly 빈도 차트용 (word → 실제 등장 횟수)
        result["keyword_counts"] = {word: counter[word] for word in top_keywords}
        result["author_stats"] = author_stats   # author dominance 요약 문자열
        result["ai_share"]     = ai_share       # ledger 기반 봇 점유율 문자열
        result["style_profile"] = style_profile
        result["composition_profile"] = composition_profile
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
        result["source_access"] = dict(raw_data.get("source_access") or {})

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

        try:
            response = self._generate_content_paced(
                label="judge_post",
                prompt=prompt,
                json_schema={
                    "type": "object",
                    "properties": {
                        "pass": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "fixed_title": {"type": "string"},
                    },
                    "required": ["pass"],
                },
                max_output_tokens=256,
                temperature=0.0,
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
