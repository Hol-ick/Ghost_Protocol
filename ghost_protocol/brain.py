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
import os
import re
from collections import Counter
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

from . import database
from . import prompt_manager as pm

# .env 에서 GEMINI_API_KEY 로딩
load_dotenv()

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
                system_instruction=pm.load("system_base.txt"),
                safety_settings=SAFETY_SETTINGS,
                temperature=0.9,
                max_output_tokens=50,
            )
            response = self._client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=_cfg,
            )
            # 디버깅: 원시 응답 출력
            raw_text = response.text.strip()
            print(f"[DEBUG] suggest_topic Raw AI Response: '{raw_text}'")

            # 마크다운 코드블록 제거 후 JSON 파싱
            cleaned = re.sub(r'```json\n|\n```|```', '', raw_text).strip()
            print(f"[DEBUG] suggest_topic Cleaned for JSON: '{cleaned}'")

            try:
                data = json.loads(cleaned)
                topic = data.get("topic", "").strip()
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
            topic: 글 주제 (예: "엔비디아 실적 발표")
            gallery_id: 갤러리 ID (예: "stockus")
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
                "'에휴' / 'ㅅㅂ' / '녹냐' / '어떡하노' / '마감' / '존버중' 같은 "
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
                "  '에휴'  /  'ㅅㅂ'  /  '녹냐'  /  '어떡하노'  /  '시발년들'\n"
                "  '계좌 녹는 거 보소'  /  '하...'  /  '존버나'\n"
                "단어 1~2개, 끝. 키워드 나열 절대 금지. 문장 완성 절대 금지.\n"
            )

        parts.append(
            f"주제: {topic}\n\n"
            f"위 주제로 디시 미주갤 스타일 게시글을 {tone_instruction}.\n"
            f"[분량 조건] {length_instruction}.\n"
            f"{cross_instruction}"
            f"{kw_inject}\n"
            "[중요] 출력은 반드시 아래와 같이 XML 태그로 감싸서 출력해라. "
            "다른 부가 설명은 절대 하지 마.\n"
            "<TITLE>여기에 제목</TITLE>\n"
            "<CONTENT>여기에 본문</CONTENT>"
        )

        prompt = "\n\n---\n\n".join(parts)

        # ── Gemini API 호출 (GenerateContentConfig + 429 안전 처리) ──
        _cfg = types.GenerateContentConfig(
            system_instruction=pm.load("system_base.txt"),
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

        # ── XML 태그 정규식 파싱 (닫는 태그 생략 허용) ──
        text = response.text.strip()

        # TITLE 추출 (닫는 태그가 없어도 줄바꿈 전까지 긁어옴, 앞뒤 공백 유연)
        title_match = re.search(
            r"<TITLE>\s*(.*?)\s*(?:</TITLE>|\n|$)", text, re.IGNORECASE | re.DOTALL
        )
        # CONTENT 추출 (닫는 태그가 없어도 문자열 끝까지 긁어옴, 앞뒤 공백 유연)
        content_match = re.search(
            r"<CONTENT>\s*(.*?)\s*(?:</CONTENT>|$)", text, re.IGNORECASE | re.DOTALL
        )

        title = title_match.group(1).strip() if title_match else "무제"
        content = content_match.group(1).strip() if content_match else text

        # 혹시 모를 태그 찌꺼기 완벽 제거
        title = re.sub(r"</?TITLE>", "", title, flags=re.IGNORECASE).strip()
        content = re.sub(r"</?CONTENT>", "", content, flags=re.IGNORECASE).strip()

        # ── 👻 Stealth Watermark: Zero-Width Space 삽입 ──
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

        # ── 1. 모든 텍스트 합치기 ──────────────────────────
        all_text = " ".join(titles + comments)

        # ── 2. 한글 토큰 추출 (2자 이상 한글 어절) ─────────
        tokens = re.findall(r"[가-힣]{2,}", all_text)

        # ── 3. 불용어 제거 + Counter ───────────────────────
        filtered    = [t for t in tokens if t not in KEYWORD_STOPWORDS]
        counter     = Counter(filtered)
        top_keywords: list[str] = [w for w, _ in counter.most_common(top_k)]

        # ── 4. Gemini 전달용 경량 페이로드 조립 ────────────
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
        )

        # ── 5. Gemini API 호출 (분석용 — 기본 safety settings 유지) ──
        cfg = types.GenerateContentConfig(
            max_output_tokens=512,
            temperature=0.3,       # 분석이므로 낮은 온도 → 일관성 ↑
        )

        try:
            response = self._client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=cfg,
            )
            raw_text = response.text.strip()

            # 마크다운 코드블록 제거 후 JSON 파싱
            cleaned  = re.sub(r"```json\n?|\n?```|```", "", raw_text).strip()
            result   = json.loads(cleaned)

        except json.JSONDecodeError:
            # JSON 파싱 실패 시 키워드 기반 fallback
            result = {
                "hot_topics": top_keywords[:3],
                "sentiment":  "분석 실패",
                "memes":      [],
                "summary":    raw_text[:200] if "raw_text" in dir() else "응답 파싱 실패",
            }
        except Exception as e:
            if self._is_rate_limit_error(e):
                raise RateLimitError(
                    "Gemini API Rate Limit 초과 (429). 잠시 후 재시도 필요."
                ) from e
            raise

        # ── 6. 공통 메타데이터 주입 ─────────────────────────
        result["top_keywords"] = top_keywords
        # keyword_counts: Plotly 빈도 차트용 (word → 실제 등장 횟수)
        result["keyword_counts"] = dict(counter.most_common(top_k))
        result["stats"] = {
            "titles_count":   len(titles),
            "comments_count": len(comments),
            "keywords_found": len(filtered),
        }

        return result
