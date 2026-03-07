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
    ) -> dict:
        """DC Inside 스타일 게시글 생성 (XML 태그 파싱).

        Args:
            topic: 글 주제 (예: "요즘 분위기 왜 이러냐")
            gallery_id: 갤러리 ID (예: "baseball_new9")
            tone: 말투 (cynical / neutral / analytical / aggressive)
            context_hours: 컨텍스트 시간 범위 (None이면 미사용)
            length: 글 길이 ("짧게 (1~2문장)" / "보통 (3~4문장)" / "길게 (5문장 이상)")
            keywords: 핫 키워드 리스트 (본문 살 붙이기용)

        Returns:
            {"title": str, "content": str}
            429 에러 시 안전한 에러 메시지 반환
        """
        tone_desc = {
            "cynical": "tone == cynical 규칙을 따라 냉소적이고 비꼬는 듯한 어조로 써",
            "neutral": "tone == neutral 규칙을 따라 감정 없이 건조하게 써. 욕설/비속어/추임새 절대 금지",
            "analytical": "tone == analytical 규칙을 따라 논리적이고 분석적으로 써. 추임새 금지",
            "monologue": "tone == monologue 규칙을 따라 배설형 독백으로 써. 추임새/감정기호 절대 금지. 허무하고 우울하게",
            "aggressive": "tone == aggressive 규칙을 따라 극도로 공격적이고 분노에 찬 어조로 써",
            "aggro": "tone == aggro 규칙을 따라 어그로 극대화. 팩트 비틀기, 극단적 단어 사용",
        }

        length_desc = {
            "아주 짧게 (1문장)": (
                "본문을 단어 1~2개 또는 탄식 파편 하나로만 끝내라. "
                "완성된 문장이 아니어도 된다. "
                "'에휴' / 'ㅅㅂ' / '어떡하노' / '아 진짜' / '이게 맞냐' 같은 "
                "단 한 마디가 정답이다. 절대 2개 이상의 문장을 쓰지 마라."
            ),
            "짧게 (1~2문장)": "본문을 1~2문장으로 짧게 작성해. 문장이 완성되지 않아도 된다",
            "보통 (3~4문장)": "본문을 정확히 3~4문장으로 작성해",
        }

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

        # monologue × 아주 짧게 교차 지시 (가장 치명적 조합 — 별도 강화)
        cross_instruction = ""
        if tone == "monologue" and length == "아주 짧게 (1문장)":
            cross_instruction = (
                "\n[⚠️ 최우선 지시: monologue × 아주 짧게 조합]\n"
                "본문은 탄식 한 방으로 끝내라. 아래 예시처럼:\n"
                "  '에휴'  /  'ㅅㅂ'  /  '어떡하노'  /  '아 진짜'  /  '이게 맞냐'\n"
                "  '하...'  /  '어카냐 진짜'  /  '무슨 일임'\n"
                "단어 1~2개, 끝. 키워드 나열 절대 금지. 문장 완성 절대 금지.\n"
            )

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
            )
        )

        prompt = "\n\n---\n\n".join(parts)

        # ── Gemini API 호출 (GenerateContentConfig + 429 안전 처리) ──
        _cfg = types.GenerateContentConfig(
            system_instruction=pm.render("system_base.txt", gallery_id=gallery_id),
            safety_settings=SAFETY_SETTINGS,
            max_output_tokens=2048,
            temperature=0.9,
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

        # ── JSON / XML 듀얼 파서 ──────────────────────────────────────────────
        # 1차: JSON 파싱 (현행 generate_post.txt 출력 형식)
        # 2차: XML 태그 파싱 (레거시 fallback — 닫는 태그 생략 허용)
        text = response.text.strip()

        _parsed_title:   str | None = None
        _parsed_content: str | None = None

        # 1차 — JSON
        try:
            _json_out       = _parse_json_robust(text)
            _parsed_title   = str(_json_out.get("title",   "")).strip() or None
            _parsed_content = str(_json_out.get("content", "")).strip() or None
        except Exception:
            pass

        # 2차 — XML fallback (JSON 파싱 실패 또는 빈 값일 때)
        if not _parsed_title and not _parsed_content:
            _tm = re.search(
                r"<TITLE>\s*(.*?)\s*(?:</TITLE>|\n|$)", text, re.IGNORECASE | re.DOTALL
            )
            _cm = re.search(
                r"<CONTENT>\s*(.*?)\s*(?:</CONTENT>|$)", text, re.IGNORECASE | re.DOTALL
            )
            _parsed_title   = _tm.group(1).strip() if _tm else None
            _parsed_content = _cm.group(1).strip() if _cm else None

        title   = re.sub(r"</?TITLE>",   "", (_parsed_title   or "무제"), flags=re.IGNORECASE).strip()
        content = re.sub(r"</?CONTENT>", "", (_parsed_content or text),   flags=re.IGNORECASE).strip()

        # ── 👻 Stealth Watermark: Zero-Width Space 삽입 ──────────────────────
        # brain.py에서 content에 ZWS 삽입 → poster.py에서 title에도 추가 삽입.
        # Echo Chamber 효과 추적: scraper.py가 제목 내 ZWS 유무로 봇 게시글 판별.
        content = content + "\u200B"

        return {
            "title": title,
            "content": content,
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

        # ── ZWS 봇 점유율 계산 ─────────────────────────────────────────────
        # scraper.collect_trending()이 주입한 ai_post_count / total_post_count를 사용.
        # 최초 분석 시 ZWS 게시글이 없으면 0/N (0.0%)으로 자연스럽게 표시됨.
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
        result["ai_share"]     = ai_share       # ZWS 봇 점유율 문자열
        result["stats"] = {
            "titles_count":    len(titles),
            "comments_count":  len(comments),
            "authors_count":   len(authors),
            "keywords_found":  len(filtered),
            "ai_post_count":   _ai_post_count,
            "total_post_count": _total_post_count,
        }

        return result
