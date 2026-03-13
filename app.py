"""Ghost Protocol v5.0 — LAUNCHPAD
One-Page Stealth Dashboard · Bento 2.0 Redesign

Pipeline: INTEL (Trend Analysis) → PAYLOAD (Topic + Config) → LAUNCH (FIRE + Monitor)
@st.fragment 기반 부분 재렌더링으로 Flickering 완전 제거.

실행: streamlit run app.py
"""

import asyncio
import concurrent.futures as _cf
import datetime
import html as _html
import json
import os
import queue
import math
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # .env 파일을 환경변수로 주입 (없어도 무해)

# ── API Key: .env → 환경변수에서 한 번만 읽어 모듈 상수로 고정 ──────────
_GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import plotly.graph_objects as go
import streamlit as st

from ghost_protocol import cycle_memory as _cm
from ghost_protocol import database
from ghost_protocol import prompt_manager as pm
from ghost_protocol.brain import GhostBrain, RateLimitError
from ghost_protocol.poster import GhostPoster, load_accounts


# ══════════════════════════════════════════════
# 공용 타임아웃 래퍼
# ══════════════════════════════════════════════
def _timed(fn, *args, _timeout: float = 30.0, **kwargs):
    """blocking 함수를 별도 스레드에서 실행, _timeout 초 내 완료 안 되면
    concurrent.futures.TimeoutError를 raise한다. 호출자가 직접 catch 할 것."""
    with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
        return _pool.submit(fn, *args, **kwargs).result(timeout=_timeout)

# ══════════════════════════════════════════════
# Page Config
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="Ghost Protocol — Launchpad",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════
# Lookup Maps (module-level constants)
# ══════════════════════════════════════════════
_TYPE_MAP = {
    "마이너 (mgallery)": "mgallery",
    "정규 (board)":      "board",
    "미니 (mini)":       "mini",
}
_TONE_MAP = {
    "🧊 냉소적 (Cynical)":         "cynical",
    "😐 중립 (Neutral)":           "neutral",
    "📊 분석적 (Analytical)":      "analytical",
    "🗣️ 독백 (Monologue)":        "monologue",
    "🔥 공격적 (Aggressive)":      "aggressive",
    "💀 어그로성 (Aggro)":         "aggro",
    "😤 하소연형 (Ventilator)":    "ventilator",
    "🔭 메타 관전자 (Meta)":       "meta_observer",
    "☠️ 체념형 (Doomer)":         "doomer",
    "🛡️ 소신발언 (Defender)":     "conviction_defender",
    "🔧 훈수꾼 (Solution)":        "solution_proposer",
    "🚀 희망회로 (Hopium)":        "hopium",
    "❓ 질문충 (Lazy Q)":          "lazy_questioner",
    "😏 비틱 (Humblebragger)":     "humblebragger",
    "🕵️ 음모론자 (Paranoid)":     "paranoid",
    "😭 자학형 (Self-deprecator)": "self_deprecator",
    "📣 집결형 (Rally Crier)":     "rally_crier",
    "📡 실황형 (Score Reporter)":  "score_reporter",
    "🔄 화제전환형 (Diverger)":    "topic_diverger",
}
_LEN_OPTS = ["아주 짧게 (1문장)", "짧게 (1~2문장)", "보통 (3~4문장)"]
_INTEL_CACHE_TTL = 900  # 15분

# ── SWARM 다중 인격 풀 — prompts/personas.json 에서 로드 ───────────────────
# 매 WAVE마다 랜덤으로 한 가지 페르소나를 선택하여 글투 다양성 확보.
# "key"는 brain.py generate_post()의 tones.json 맵과 1:1 대응.
# UI의 고정 톤 설정을 SWARM 내에서 오버라이드함 — 현지인 군중 시뮬레이션.
_PERSONA_POOL: list[dict] = pm.load_json("personas.json")

# 입체적 '돌연변이' 캐릭터 — 매 배치에 2~3개 강제 배정하여 서사 갈등 보장
_MUTANT_KEYS: frozenset[str] = frozenset({"conviction_defender", "solution_proposer", "hopium"})
_MUTANT_POOL: list[dict] = [p for p in _PERSONA_POOL if p["key"] in _MUTANT_KEYS]

# ── 감정 온도 티어 — 파멸 루프(연속 극단적 페르소나 누적) 방지 ─────────────────
# HOT  : 분노·공격·체념·음모론 — 갤러리를 부정 방향으로 끌어내리는 페르소나
# NEUTRAL: 건조·분석·관전·중계 — 감정 온도를 리셋하는 완충 페르소나
# WARM : 나머지 (냉소·독백·질문 등) — 중간 온도
# 배치 규칙: HOT ≤ 30%, NEUTRAL ≥ 20%, 연속 HOT 3회 이상 불가
_PERSONA_HOT_KEYS: frozenset[str] = frozenset({
    "aggressive", "aggro", "doomer", "paranoid",
})
_PERSONA_NEUTRAL_KEYS: frozenset[str] = frozenset({
    "neutral", "analytical", "meta_observer", "score_reporter",
})
_HOT_POOL:     list[dict] = [p for p in _PERSONA_POOL if p["key"] in _PERSONA_HOT_KEYS]
_NEUTRAL_POOL: list[dict] = [p for p in _PERSONA_POOL if p["key"] in _PERSONA_NEUTRAL_KEYS]
_WARM_POOL:    list[dict] = [
    p for p in _PERSONA_POOL
    if p["key"] not in _PERSONA_HOT_KEYS
    and p["key"] not in _PERSONA_NEUTRAL_KEYS
    and p["key"] not in _MUTANT_KEYS
]


def _fix_consecutive_same(lineup: list[dict]) -> list[dict]:
    """동일 페르소나가 연속 2회 이상 이어지지 않도록 swap으로 재배치."""
    result = list(lineup)
    for i in range(1, len(result)):
        if result[i]["key"] == result[i - 1]["key"]:
            swapped = False
            for j in range(i + 1, len(result)):
                if result[j]["key"] != result[i]["key"]:
                    result[i], result[j] = result[j], result[i]
                    swapped = True
                    break
            if not swapped:
                for j in range(i - 2, -1, -1):
                    if result[j]["key"] != result[i]["key"]:
                        result[i], result[j] = result[j], result[i]
                        break
    return result


def _fix_consecutive_hot(lineup: list[dict]) -> list[dict]:
    """연속 HOT 페르소나가 3회 이상 이어지지 않도록 swap으로 재배치."""
    result = list(lineup)
    for i in range(2, len(result)):
        if (result[i]["key"] in _PERSONA_HOT_KEYS
                and result[i - 1]["key"] in _PERSONA_HOT_KEYS
                and result[i - 2]["key"] in _PERSONA_HOT_KEYS):
            # i 이후에서 non-HOT 찾아 swap
            swapped = False
            for j in range(i + 1, len(result)):
                if result[j]["key"] not in _PERSONA_HOT_KEYS:
                    result[i], result[j] = result[j], result[i]
                    swapped = True
                    break
            if not swapped:
                # 뒤에 non-HOT 없으면 i 이전에서 찾기
                for j in range(i - 3, -1, -1):
                    if result[j]["key"] not in _PERSONA_HOT_KEYS:
                        result[i], result[j] = result[j], result[i]
                        break
    return result


def _sample_capped(pool: list[dict], n: int, max_per_key: int = 3) -> list[dict]:
    """pool에서 n개를 뽑되, 동일 key는 max_per_key 초과 금지.

    cap을 넘는 key가 없는 후보가 있을 경우 그 안에서만 고름.
    모든 key가 cap에 닿으면 cap 무시하고 랜덤 선택 (극단적 pool 부족 방어).
    """
    result: list[dict] = []
    counts: dict[str, int] = {}
    for _ in range(n):
        available = [p for p in pool if counts.get(p["key"], 0) < max_per_key]
        chosen = random.choice(available if available else pool)
        result.append(chosen)
        counts[chosen["key"]] = counts.get(chosen["key"], 0) + 1
    return result


def _build_balanced_lineup(
    wave_count: int,
    *,
    sentiment_score: int = 0,
    hour: int = -1,
) -> list[dict]:
    """온도 밸런싱된 Wave 라인업을 빌드한다.

    기본 보장 조건:
    - mutant(conviction_defender / solution_proposer / hopium): 2~3개 고정
    - HOT(aggressive / aggro / doomer / paranoid): 최대 floor(30%)개, 최소 1개
    - NEUTRAL(neutral / analytical / meta_observer / score_reporter): 최소 ceil(20%)개
    - 나머지 슬롯은 WARM(cynical / monologue / ventilator 등)으로 채움
    - 동일 key 페르소나 최대 3개 (_sample_capped 적용)
    - 동일 페르소나 연속 2회 불가 (_fix_consecutive_same 후처리)
    - 연속 HOT 3회 이상 불가 (_fix_consecutive_hot 후처리)

    추가 보정:
    - sentiment_score ≤ -2 (감성 drift): HOT 상한 15%로 축소, mutant 최대치 강제
    - hour 기반 시간대 리듬:
        심야(23~3)  → HOT cap +10%, monologue WARM 가중 2배
        출근(7~9)   → cynical / lazy_questioner WARM 가중 2배
        점심(12~13) → humblebragger / rally_crier WARM 가중 2배
        저녁(20~22) → self_deprecator / topic_diverger WARM 가중 2배
    """
    # ── 감성 drift 보정 ─────────────────────────────────────────────────────
    _is_drifted = sentiment_score <= _cm.DRIFT_THRESHOLD
    _hot_ratio  = 0.15 if _is_drifted else 0.30

    # ── 시간대 HOT cap 미세 조정 ────────────────────────────────────────────
    _LATE_NIGHT: frozenset[int] = frozenset({23, 0, 1, 2, 3})
    _RUSH_HOUR:  frozenset[int] = frozenset({7, 8, 9})
    _LUNCH:      frozenset[int] = frozenset({12, 13})
    _EVENING:    frozenset[int] = frozenset({20, 21, 22})

    if hour in _LATE_NIGHT and not _is_drifted:
        _hot_ratio = min(0.40, _hot_ratio + 0.10)   # 심야 HOT cap +10%

    max_hot     = max(1, int(wave_count * _hot_ratio))
    min_neutral = max(1, math.ceil(wave_count * 0.20))

    # ── mutant 강제 배정 ─────────────────────────────────────────────────────
    # drift 시 mutant(hopium/solution_proposer) 최대치 강제 → 긍정 발화 보장
    if _is_drifted:
        mutant_count = min(3, wave_count, len(_MUTANT_POOL))
    else:
        mutant_count = random.randint(2, min(3, wave_count, len(_MUTANT_POOL)))
    remaining = wave_count - mutant_count

    # ── HOT 배정 (최소 1개 보장) ─────────────────────────────────────────────
    hot_count = (random.randint(1, min(max_hot, remaining))
                 if remaining > 0 else 0)
    remaining -= hot_count

    # ── NEUTRAL 최소 보장 ────────────────────────────────────────────────────
    neutral_count = min(min_neutral + random.randint(0, 2), remaining)
    neutral_count = max(0, neutral_count)
    remaining -= neutral_count

    warm_count = max(0, remaining)

    # ── 시간대 기반 WARM 가중치 조정 ────────────────────────────────────────
    # 원본 _WARM_POOL 보존; 복사본에 중복 삽입 → _sample_capped가 확률 반영
    _warm_weighted = list(_WARM_POOL)
    if hour in _LATE_NIGHT:
        # 심야: 독백(monologue) 2배 — 새벽 감성글 시뮬레이션
        _warm_weighted += [p for p in _WARM_POOL if p["key"] == "monologue"]
    elif hour in _RUSH_HOUR:
        # 출근길: cynical + lazy_questioner 2배 — 짧고 빠른 반응
        _warm_weighted += [p for p in _WARM_POOL if p["key"] in ("cynical", "lazy_questioner")]
    elif hour in _LUNCH:
        # 점심: humblebragger + rally_crier 2배 — 자랑·선동 분위기
        _warm_weighted += [p for p in _WARM_POOL if p["key"] in ("humblebragger", "rally_crier")]
    elif hour in _EVENING:
        # 저녁: self_deprecator + topic_diverger 2배 — 퇴근 후 뒤풀이 분위기
        _warm_weighted += [p for p in _WARM_POOL if p["key"] in ("self_deprecator", "topic_diverger")]

    slots = (
        random.sample(_MUTANT_POOL, mutant_count)
        + _sample_capped(_HOT_POOL,        hot_count)
        + _sample_capped(_NEUTRAL_POOL,    neutral_count)
        + _sample_capped(_warm_weighted,   warm_count)
    )
    random.shuffle(slots)
    slots = _fix_consecutive_same(slots)   # 동일 페르소나 연속 2회 방지
    return _fix_consecutive_hot(slots)     # HOT 연속 3회 방지

# ══════════════════════════════════════════════
# Gallery History — 갤러리 히스토리 퀵셀렉트
# ══════════════════════════════════════════════
_GALLERY_HISTORY_PATH = "gallery_history.json"
_HISTORY_MAX = 8  # 최대 저장 항목 수


def _history_load() -> list[dict]:
    """로컬 갤러리 히스토리를 로드. 파일 없거나 손상 시 빈 리스트 반환."""
    try:
        with open(_GALLERY_HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _history_save(gallery_id: str, type_label: str) -> None:
    """갤러리 ID + 타입을 히스토리에 최신순으로 저장 (중복 제거, 최대 _HISTORY_MAX)."""
    if not gallery_id.strip():
        return
    data = _history_load()
    # 동일 gallery_id 기존 항목 제거 후 맨 앞에 삽입 (최신순)
    data = [e for e in data if e.get("gallery_id") != gallery_id]
    data.insert(0, {"gallery_id": gallery_id, "type_label": type_label})
    data = data[:_HISTORY_MAX]
    try:
        with open(_GALLERY_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 파일 쓰기 실패는 무시 (UX 차단 방지)


# ══════════════════════════════════════════════
# CSS — Stealth Dark Bento Theme 2.0
# ══════════════════════════════════════════════
st.markdown("""
<style>
    /* ═══ 1. 전역 다크 베이스 — Nuclear Override ═══ */
    html, body {
        background-color: #0E1117 !important;
        color: #FAFAFA !important;
    }
    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    .stMain,
    .main,
    section.main,
    footer {
        background-color: #0E1117 !important;
        color: #FAFAFA !important;
    }
    [data-testid="stHeader"],
    .stApp header[data-testid="stHeader"] {
        background-color: #0E1117 !important;
    }
    [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"],
    [data-testid="column"] {
        background-color: transparent !important;
    }

    /* ═══ 2. 사이드바 완전 제거 ═══ */
    [data-testid="collapsedControl"] { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }

    /* ═══ 3. 메인 패딩 조정 ═══ */
    .stMainBlockContainer {
        padding: 1.5rem 2.5rem 4rem 2.5rem !important;
        max-width: 1440px !important;
        margin: 0 auto !important;
    }

    /* ═══ 4. 입력 필드 ═══ */
    div[data-baseweb="input"] {
        background-color: #1E1E1E !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: #00F0FF !important;
        box-shadow: 0 0 0 2px rgba(0,240,255,0.15) !important;
    }
    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] input {
        background-color: #1E1E1E !important;
        color: #FAFAFA !important;
        -webkit-text-fill-color: #FAFAFA !important;
    }
    ul[role="listbox"] { background-color: #1E1E1E !important; }
    li[role="option"] { color: #FAFAFA !important; }
    li[role="option"]:hover, li[role="option"][aria-selected="true"] {
        background-color: #2A2A2A !important; color: #00F0FF !important;
    }
    div[data-baseweb="popover"], div[data-baseweb="popover"] > div {
        background-color: #1E1E1E !important;
    }
    .stTextInput input, .stTextArea textarea {
        background-color: #1E1E1E !important; color: #FAFAFA !important;
        -webkit-text-fill-color: #FAFAFA !important;
    }

    /* ═══ 5. 버튼 기본 ═══ */
    div.stButton > button {
        background-color: #1E1E1E !important;
        color: #FAFAFA !important;
        border: 1px solid rgba(255,255,255,0.15) !important;
        border-radius: 12px !important;
        font-weight: 700 !important;
        transition: all 0.2s !important;
    }
    div.stButton > button:hover {
        background-color: #2A2A2A !important;
        border-color: rgba(255,255,255,0.3) !important;
    }

    /* ═══ 6. FIRE 버튼 ═══ */
    .fire-btn > button {
        background: #FF4B4B !important;
        color: #FFFFFF !important;
        font-size: 1.05rem !important;
        font-weight: 900 !important;
        letter-spacing: 4px !important;
        text-transform: uppercase !important;
        padding: 0.85rem 2rem !important;
        border-radius: 14px !important;
        border: none !important;
        box-shadow: 0 6px 24px rgba(255,75,75,0.45) !important;
        transition: all 0.2s !important;
    }
    .fire-btn > button:hover {
        background: #FF2222 !important;
        box-shadow: 0 8px 32px rgba(255,75,75,0.65) !important;
        transform: translateY(-2px) !important;
    }
    .fire-btn > button:disabled {
        background: #3D3D3D !important;
        box-shadow: none !important;
        transform: none !important;
        opacity: 0.5 !important;
    }

    /* ═══ 7. STOP 버튼 ═══ */
    .stop-btn > button {
        background: #1A1A1A !important;
        color: #FF4B4B !important;
        border: 1px solid rgba(255,75,75,0.4) !important;
        border-radius: 12px !important;
        font-weight: 700 !important;
        letter-spacing: 2px !important;
        transition: all 0.2s !important;
    }
    .stop-btn > button:hover {
        background: rgba(255,75,75,0.1) !important;
        border-color: #FF4B4B !important;
        box-shadow: 0 0 14px rgba(255,75,75,0.25) !important;
    }

    /* ═══ 8. Live Terminal ═══ */
    .terminal {
        background: #000000 !important;
        border: 1px solid rgba(0,255,0,0.15) !important;
        border-radius: 12px !important;
        padding: 16px !important;
        overflow-y: auto !important;
        font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
        font-size: 0.76rem !important;
        line-height: 1.6 !important;
        color: #00FF00 !important;
    }
    .terminal div { padding: 1px 0 !important; }
    .t-ok   { color: #00FF00 !important; }
    .t-err  { color: #FF4B4B !important; font-weight: 600 !important; }
    .t-info { color: #00F0FF !important; }
    .t-warn { color: #FFD700 !important; }
    .t-wave { color: #BC8CFF !important; font-weight: 700 !important; letter-spacing: 1px !important; }

    /* ═══ 9. Preview 카드 ═══ */
    .preview-dark {
        background: #1E1E1E !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        padding: 22px !important;
        min-height: 360px !important;
    }
    .pd-label {
        color: #BC8CFF !important; font-size: 0.65rem !important; font-weight: 700 !important;
        letter-spacing: 3px !important; text-transform: uppercase !important; margin-bottom: 10px !important;
    }
    .pd-title {
        color: #FAFAFA !important; font-size: 1.05rem !important; font-weight: 700 !important;
        margin-bottom: 14px !important; padding-bottom: 12px !important;
        border-bottom: 1px solid rgba(255,255,255,0.1) !important; line-height: 1.4 !important;
    }
    .pd-body { color: #CCCCCC !important; font-size: 0.9rem !important; line-height: 1.75 !important; white-space: pre-wrap !important; }
    .pd-empty { color: #555555 !important; font-style: italic !important; text-align: center !important; padding: 60px 0 !important; font-size: 0.85rem !important; }

    /* ═══ 10. 섹션 헤더 ═══ */
    .section-hdr {
        font-size: 0.72rem !important; font-weight: 700 !important; letter-spacing: 2.5px !important;
        text-transform: uppercase !important; color: #888888 !important; margin-bottom: 12px !important;
    }

    /* ═══ 11. Progress Bar ═══ */
    .stProgress > div > div { background: linear-gradient(90deg, #FF4B4B, #BC8CFF) !important; }

    /* ═══ 12. INTEL 브리핑 카드 ═══ */
    .intel-card {
        background: #141820 !important; border: 1px solid rgba(0,240,255,0.18) !important;
        border-radius: 18px !important; padding: 24px 28px !important; margin-top: 8px !important;
    }
    .intel-header {
        display: flex !important; align-items: center !important; gap: 10px !important;
        margin-bottom: 18px !important; border-bottom: 1px solid rgba(0,240,255,0.12) !important;
        padding-bottom: 12px !important;
    }
    .intel-title {
        color: #00F0FF !important; font-size: 0.72rem !important; font-weight: 800 !important;
        letter-spacing: 4px !important; text-transform: uppercase !important;
        text-shadow: 0 0 10px rgba(0,240,255,0.4) !important;
    }
    .intel-gallery-badge {
        background: rgba(0,240,255,0.08) !important; border: 1px solid rgba(0,240,255,0.25) !important;
        border-radius: 20px !important; padding: 2px 10px !important; color: #00F0FF !important;
        font-size: 0.65rem !important; font-family: monospace !important;
    }
    .intel-cache-ts { margin-left: auto !important; color: #444 !important; font-size: 0.62rem !important; font-family: monospace !important; }
    .intel-sentiment {
        display: inline-block !important; padding: 4px 14px !important; border-radius: 20px !important;
        font-size: 0.78rem !important; font-weight: 700 !important; letter-spacing: 1px !important; margin-bottom: 16px !important;
    }
    .intel-sentiment-panic    { background: rgba(255,75,75,0.15) !important; color: #FF4B4B !important; border: 1px solid rgba(255,75,75,0.35) !important; }
    .intel-sentiment-hostile  { background: rgba(255,100,0,0.15) !important; color: #FF6400 !important; border: 1px solid rgba(255,100,0,0.35) !important; }
    .intel-sentiment-mock     { background: rgba(188,140,255,0.15) !important; color: #BC8CFF !important; border: 1px solid rgba(188,140,255,0.35) !important; }
    .intel-sentiment-friendly { background: rgba(0,255,0,0.1) !important; color: #00FF88 !important; border: 1px solid rgba(0,255,0,0.3) !important; }
    .intel-sentiment-neutral  { background: rgba(255,255,255,0.07) !important; color: #AAAAAA !important; border: 1px solid rgba(255,255,255,0.15) !important; }
    .intel-section-label {
        color: #555 !important; font-size: 0.62rem !important; font-weight: 700 !important;
        letter-spacing: 2px !important; text-transform: uppercase !important; margin-bottom: 8px !important;
    }
    .intel-chips { display: flex !important; flex-wrap: wrap !important; gap: 6px !important; margin-bottom: 14px !important; }
    .intel-chip-hot  { background: rgba(255,75,75,0.12) !important; border: 1px solid rgba(255,75,75,0.3) !important; border-radius: 20px !important; padding: 3px 10px !important; color: #FF8080 !important; font-size: 0.73rem !important; font-weight: 600 !important; }
    .intel-chip-kw   { background: rgba(255,255,255,0.05) !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 20px !important; padding: 2px 8px !important; color: #888 !important; font-size: 0.65rem !important; }
    .intel-chip-meme { background: rgba(188,140,255,0.1) !important; border: 1px solid rgba(188,140,255,0.25) !important; border-radius: 20px !important; padding: 3px 10px !important; color: #BC8CFF !important; font-size: 0.73rem !important; }
    .intel-summary   { color: #CCCCCC !important; font-size: 0.85rem !important; line-height: 1.7 !important; border-left: 2px solid rgba(0,240,255,0.25) !important; padding-left: 12px !important; margin-top: 4px !important; }
    .intel-stats     { display: flex !important; gap: 10px !important; margin-top: 14px !important; padding-top: 12px !important; border-top: 1px solid rgba(255,255,255,0.06) !important; }
    .intel-stat-pill { background: rgba(255,255,255,0.04) !important; border: 1px solid rgba(255,255,255,0.08) !important; border-radius: 8px !important; padding: 4px 10px !important; color: #666 !important; font-size: 0.62rem !important; font-family: monospace !important; }
    .intel-stat-pill span { color: #AAAAAA !important; font-weight: 600 !important; }
    .intel-empty     { text-align: center !important; padding: 40px 0 !important; color: #333 !important; font-size: 0.82rem !important; }
    .intel-terminal  { background: #0A0A0A !important; border: 1px solid rgba(0,240,255,0.08) !important; border-radius: 10px !important; padding: 12px 14px !important; font-family: monospace !important; font-size: 0.72rem !important; color: #00C8FF !important; line-height: 1.55 !important; overflow-y: auto !important; }
    .intel-run-btn > button {
        background: linear-gradient(135deg, #003D5C, #005580) !important; color: #00F0FF !important;
        border: 1px solid rgba(0,240,255,0.35) !important; border-radius: 12px !important;
        font-weight: 800 !important; letter-spacing: 2px !important; text-transform: uppercase !important; transition: all 0.2s !important;
    }
    .intel-run-btn > button:hover {
        background: linear-gradient(135deg, #005580, #0077AA) !important;
        box-shadow: 0 4px 18px rgba(0,240,255,0.25) !important; border-color: rgba(0,240,255,0.6) !important;
    }
    .intel-run-btn > button:disabled {
        background: #1A1A1A !important; color: #444 !important;
        border-color: rgba(255,255,255,0.08) !important; box-shadow: none !important;
    }

    /* ═══ 13. NEW: Header Bar ═══ */
    .header-bar {
        display: flex !important; align-items: center !important;
        justify-content: space-between !important;
        padding: 6px 0 18px 0 !important;
        border-bottom: 1px solid rgba(255,255,255,0.06) !important;
        margin-bottom: 22px !important;
    }
    .logo-text {
        font-size: 1.1rem !important; font-weight: 900 !important;
        letter-spacing: 3px !important; color: #FAFAFA !important;
    }
    .logo-text span { color: #00F0FF !important; }
    .logo-sub {
        font-size: 0.63rem !important; color: #555555 !important;
        letter-spacing: 2px !important; text-transform: uppercase !important; margin-top: 2px !important;
    }

    /* ═══ 14. NEW: Bento Step 카드 ═══ */
    .bento-step {
        background: #111418 !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 18px !important;
        padding: 22px 26px !important;
        margin-bottom: 14px !important;
    }
    .bento-step-header {
        display: flex !important; align-items: center !important;
        gap: 10px !important; margin-bottom: 18px !important;
    }
    .bento-step-title {
        font-size: 0.72rem !important; font-weight: 800 !important; letter-spacing: 3px !important;
        text-transform: uppercase !important; color: #00F0FF !important;
        text-shadow: 0 0 12px rgba(0,240,255,0.35) !important;
    }
    .bento-step-badge {
        display: inline-block !important; background: rgba(0,240,255,0.08) !important;
        border: 1px solid rgba(0,240,255,0.18) !important; border-radius: 20px !important;
        padding: 2px 10px !important; font-size: 0.6rem !important; font-weight: 600 !important;
        color: #00F0FF !important; letter-spacing: 1.5px !important;
    }

    /* ═══ 15. NEW: Mission Stats Bar (인라인) ═══ */
    .mission-stats-bar {
        display: flex !important; gap: 10px !important;
        margin-top: 14px !important; padding-top: 14px !important;
        border-top: 1px solid rgba(255,255,255,0.06) !important;
        flex-wrap: wrap !important; align-items: center !important;
    }
    .ms-pill {
        background: #1A1A1A !important; border: 1px solid rgba(255,255,255,0.09) !important;
        border-radius: 10px !important; padding: 8px 18px !important;
        text-align: center !important; min-width: 76px !important;
    }
    .ms-val  { font-size: 1.3rem !important; font-weight: 800 !important; line-height: 1.2 !important; }
    .ms-lbl  { font-size: 0.6rem !important; color: #666 !important; text-transform: uppercase !important; letter-spacing: 1px !important; margin-top: 2px !important; }
    .ms-ok   .ms-val { color: #00FF00 !important; }
    .ms-err  .ms-val { color: #FF4B4B !important; }
    .ms-wave .ms-val { color: #BC8CFF !important; }
    .ms-reset-wrap { margin-left: auto !important; }

    /* ═══ 16. NEW: Settings Popover 버튼 ═══ */
    .settings-wrap [data-testid="stPopoverTrigger"] > button {
        background: #1A1A1A !important; color: #888888 !important;
        border: 1px solid rgba(255,255,255,0.12) !important; border-radius: 10px !important;
        font-size: 0.75rem !important; font-weight: 600 !important; letter-spacing: 1px !important;
    }
    .settings-wrap [data-testid="stPopoverTrigger"] > button:hover {
        background: #222222 !important; color: #FAFAFA !important;
        border-color: rgba(255,255,255,0.25) !important;
    }
    /* Popover 패널 다크 */
    [data-testid="stPopoverBody"] {
        background: #161B22 !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
    }

    /* ═══ 17. NEW: Expander INTEL 스타일 ═══ */
    [data-testid="stExpander"] {
        background: #0F1318 !important;
        border: 1px solid rgba(0,240,255,0.12) !important;
        border-radius: 16px !important;
        margin-bottom: 14px !important;
        overflow: hidden !important;
    }
    [data-testid="stExpander"] summary {
        padding: 14px 22px !important;
    }
    [data-testid="stExpander"] summary:hover {
        background: rgba(0,240,255,0.04) !important;
    }
    [data-testid="stExpander"] summary p,
    [data-testid="stExpander"] summary span {
        color: #00F0FF !important;
        font-size: 0.73rem !important;
        font-weight: 700 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
    }

    /* ═══ 18. NEW: "FIRE 주제로 사용" 버튼 ═══ */
    .topic-use-btn > button {
        background: rgba(0,240,255,0.06) !important; color: #00F0FF !important;
        border: 1px solid rgba(0,240,255,0.25) !important; border-radius: 8px !important;
        font-size: 0.72rem !important; font-weight: 600 !important; letter-spacing: 1px !important;
    }
    .topic-use-btn > button:hover {
        background: rgba(0,240,255,0.12) !important;
        box-shadow: 0 0 10px rgba(0,240,255,0.15) !important;
    }

    /* ═══ 19. NEW: Config Summary 인포 박스 ═══ */
    .config-summary {
        background: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 10px !important; padding: 14px 16px !important;
    }
    .cs-row { display: flex !important; justify-content: space-between !important; align-items: center !important; margin-bottom: 6px !important; }
    .cs-row:last-child { margin-bottom: 0 !important; }
    .cs-label { color: #666 !important; font-size: 0.65rem !important; letter-spacing: 1px !important; text-transform: uppercase !important; }
    .cs-val   { color: #CCCCCC !important; font-size: 0.75rem !important; font-weight: 600 !important; font-family: monospace !important; }

    /* ═══ 20. NEW: Left Control Panel Cards (Bento 3.0) ═══ */
    .ctrl-card {
        background: #111418 !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 16px !important;
        padding: 18px 20px !important;
        margin-bottom: 12px !important;
    }
    .ctrl-card-hdr {
        font-size: 0.68rem !important; font-weight: 800 !important;
        letter-spacing: 3px !important; text-transform: uppercase !important;
        color: #00F0FF !important; text-shadow: 0 0 10px rgba(0,240,255,0.3) !important;
        margin-bottom: 14px !important;
    }

    /* ═══ 21. NEW: 대본 제작 버튼 (GENERATE) ═══ */
    .generate-btn > button {
        background: linear-gradient(135deg, #1A3A1A, #1F5C1F) !important;
        color: #00FF88 !important;
        font-size: 1.05rem !important; font-weight: 900 !important;
        letter-spacing: 4px !important; text-transform: uppercase !important;
        padding: 0.85rem 2rem !important; border-radius: 14px !important;
        border: 1px solid rgba(0,255,136,0.35) !important;
        box-shadow: 0 6px 24px rgba(0,255,136,0.25) !important;
        transition: all 0.2s !important;
    }
    .generate-btn > button:hover {
        background: linear-gradient(135deg, #1F5C1F, #2A7A2A) !important;
        box-shadow: 0 8px 32px rgba(0,255,136,0.4) !important;
        transform: translateY(-2px) !important;
    }
    .generate-btn > button:disabled {
        background: #1A1A1A !important; color: #444 !important;
        box-shadow: none !important; transform: none !important; opacity: 0.5 !important;
        border-color: rgba(255,255,255,0.08) !important;
    }

    /* ═══ 22. NEW: 대본 최종 승인 버튼 (CONFIRM) ═══ */
    .confirm-btn > button {
        background: linear-gradient(135deg, #2A4A00, #3D6E00) !important;
        color: #AAFF44 !important;
        font-size: 1.08rem !important; font-weight: 900 !important;
        letter-spacing: 3px !important;
        padding: 1rem 2rem !important; border-radius: 14px !important;
        border: 1px solid rgba(170,255,68,0.4) !important;
        box-shadow: 0 6px 28px rgba(170,255,68,0.3) !important;
        transition: all 0.2s !important;
    }
    .confirm-btn > button:hover {
        background: linear-gradient(135deg, #3D6E00, #527A00) !important;
        box-shadow: 0 8px 36px rgba(170,255,68,0.5) !important;
        transform: translateY(-2px) !important;
    }

    /* ═══ 23. NEW: Review Card ═══ */
    .review-card {
        background: #12161C !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 12px !important;
        padding: 14px 18px !important;
        margin-bottom: 10px !important;
    }
    .review-card-failed {
        background: #160A0A !important;
        border-color: rgba(255,75,75,0.2) !important;
    }
    .rc-wave-badge {
        color: #BC8CFF !important; font-size: 0.62rem !important;
        font-weight: 700 !important; letter-spacing: 2px !important;
        text-transform: uppercase !important;
    }
    .rc-title {
        color: #FAFAFA !important; font-size: 0.9rem !important;
        font-weight: 700 !important; margin: 8px 0 6px 0 !important;
        line-height: 1.4 !important;
    }
    .rc-body {
        color: #888888 !important; font-size: 0.78rem !important;
        line-height: 1.6 !important; max-height: 72px !important;
        overflow-y: hidden !important; white-space: pre-wrap !important;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════
def _init_state() -> None:
    defaults: dict = {
        # ── Worker 통신 ──────────────────────────────
        "swarm_log":              [],
        "swarm_preview_title":    "",
        "swarm_preview_content":  "",
        "swarm_wave_current":     0,
        "swarm_wave_total":       0,
        "posts_success":          0,
        "posts_failed":           0,
        "last_fired":             False,
        "swarm_running":          False,
        "swarm_queue":            None,
        "swarm_stop_event":       None,
        "swarm_infinite":         False,
        # ── Batch Generation (Human-in-the-loop) ─────────────────────
        "batch_generating":       False,   # 대본 일괄 생성 중
        "batch_gen_queue":        None,
        "batch_gen_stop_event":   None,
        "review_scripts":         [],      # 생성된 대본 목록 [{wave, persona_name, tone, title, content, target_comments, _failed}]
        "review_ready":           False,   # 검수 보드 표시 상태
        "_batch_gen_config":      {},      # 무한 모드 재배치용 설정 저장
        "_show_copy_box":         False,  # 검수 보드 전체 복사 토글
        # ── INTEL ────────────────────────────────────
        "intel_running":          False,
        "intel_queue":            None,
        "intel_log":              [],
        "intel_result":           None,
        "intel_cache":            {},
        # ── Plotly 차트 캐시 ─────────────────────────
        "_intel_fig":             None,
        "_intel_fig_key":         None,
        # ── Widget 기본값 (Settings Popover) ─────────
        "target_tone_label":      "🧊 냉소적 (Cynical)",
        "target_length":          "보통 (3~4문장)",
        "target_headless":        True,
        # ── Widget 기본값 (Payload Bento) ────────────
        "target_gallery_id":      "",
        "target_type_label":      "마이너 (mgallery)",
        "swarm_topic_input":      "",
        "swarm_wave_count":       3,
        # ── Widget 기본값 (INTEL Bento) ───────────────
        "intel_gallery_id":       "",
        "intel_type_label":       "마이너 (mgallery)",
        "intel_pages":            3,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ══════════════════════════════════════════════
# 백그라운드 워커 — threading.Thread 기반
# ══════════════════════════════════════════════

def _interruptible_sleep(seconds: float, stop_event: threading.Event, interval: float = 0.5) -> None:
    """stop_event가 set되면 즉시 중단하는 분할 sleep."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if stop_event.is_set():
            return
        time.sleep(min(interval, deadline - time.time()))


def _swarm_worker(
    log_q: queue.Queue,
    stop_ev: threading.Event,
    *,
    api_key: str,
    topic: str,
    wave_count: int,
    gallery_id: str,
    gallery_type: str,
    tone: str,
    length: str,
    headless: bool,
    infinite: bool = False,
) -> None:
    """백그라운드 스레드: Swarm Loop 전체를 실행.
    UI와는 오직 queue.Queue를 통해서만 통신한다.
    infinite=True 시: wave_count 사이클 완료 후 10~30분 쿨타임 → 무한 반복.
    중단은 stop_ev.set() (기존 🛑 STOP 버튼) 으로 안전하게 처리됨.
    """

    def q_log(msg: str) -> None:
        log_q.put({"type": "log", "data": msg})

    def q_preview(title: str, content: str, wave: int, status: str) -> None:
        log_q.put({"type": "preview", "title": title, "content": content,
                   "wave": wave, "status": status})

    def q_stat(success: int = 0, fail: int = 0) -> None:
        log_q.put({"type": "stat", "success": success, "fail": fail})

    try:
        brain = GhostBrain(api_key=api_key or None)
        database.init_db()
    except Exception as e:
        q_log(f"❌ Brain 초기화 실패: {str(e)[:120]}")
        log_q.put({"type": "done"})
        return

    # ── 계정 큐 초기화: load_accounts()는 이미 shuffle 완료 ─────────────────
    # 큐 방식: 각 Wave마다 순서대로 계정을 소비 → 큐 소진 시 재충전 + 재셔플
    # random.choice() 방식 대비 동일 계정 연속 선택 위험 제거.
    try:
        _account_pool = load_accounts()
    except (FileNotFoundError, ValueError) as _ae:
        q_log(f"❌ 계정 로드 실패 — SWARM 중단: {str(_ae)[:120]}")
        log_q.put({"type": "done"})
        return
    _account_queue: list[dict] = list(_account_pool)

    # ── 댓글 타겟 풀 수집 + 기존 댓글 프리패치 (SWARM 시작 시 1회 스냅샷) ──────
    _enriched_pool: list[dict] = []
    try:
        from ghost_protocol.scraper import TrendScraper as _TS
        _ts = _TS()
        _raw_list = _ts.fetch_post_list(gallery_id, gallery_type, page=1)
        _candidates = [p for p in _raw_list if not p.get("is_bot")][:15]
        for _c in _candidates:
            _cmts: list[str] = []
            try:
                _cmts = _ts.fetch_comments_ajax(gallery_id, _c["post_no"], gallery_type)[:5]
            except Exception:
                pass
            _enriched_pool.append({
                "post_no":           _c["post_no"],
                "title":             _c["title"],
                "existing_comments": _cmts,
            })
        q_log(f"[SWARM] 📋 댓글 타겟 풀: {len(_enriched_pool)}개 (맥락 프리패치 완료)")
    except Exception as _te:
        q_log(f"[SWARM] ⚠️ 댓글 타겟 수집 실패 (SWARM 계속): {str(_te)[:80]}")

    _global_wave = 0
    _cycle       = 0

    while True:
        _cycle += 1
        if infinite:
            q_log(f"[∞] 🔁 사이클 {_cycle} 시작 — {wave_count} WAVES 예정")

        for wave in range(1, wave_count + 1):
            if stop_ev.is_set():
                q_log("[SWARM] 🛑 중단 요청 — 루프 종료")
                break
            _global_wave += 1

            _wave_hdr = (
                f"WAVE {_global_wave} (사이클 {_cycle}-{wave}/{wave_count})" if infinite
                else f"WAVE {wave}/{wave_count}"
            )
            q_log(f"═══════ {_wave_hdr} ═══════")
            q_log(f"[W{wave}] 🧠 AI 작문 시작 → 주제: '{topic[:30]}'")
            q_preview("", "", wave, "GENERATING")

            gen_title: str | None = None
            gen_content: str = ""
            _tc_list: list[dict] = []   # Wave 스코프 초기화 — 항상 정의됨 보장

            # ── 다중 인격 랜덤 배정 ─────────────────────────────────────────
            # UI 톤 설정을 오버라이드하여 매 Wave마다 다른 현지인 말투로 작성.
            _persona   = random.choice(_PERSONA_POOL)
            _wave_tone = _persona["key"]
            q_log(f"[W{wave}] 🎭 부여된 페르소나: {_persona['name']} ({_wave_tone})")

            for attempt in range(3):
                if stop_ev.is_set():
                    break
                try:
                    _wave_targets = (
                        random.sample(_enriched_pool, min(5, len(_enriched_pool)))
                        if _enriched_pool else None
                    )
                    result = brain.generate_post(
                        topic=topic,
                        gallery_id=gallery_id,
                        tone=_wave_tone,
                        context_hours=None,
                        length=length,
                        recent_posts=_wave_targets,
                    )
                    # ── Fail-Safe: 파싱 실패 시 WAVE 즉시 Abort ──────────────
                    # "_parse_error" 플래그 또는 빈 title/content → raw 텍스트 포스팅 원천 차단
                    # target_comments 실패는 Wave Abort 사유가 아님 (빈 배열로 safe fallback)
                    if result.get("_parse_error") or not result.get("title") or not result.get("content"):
                        q_log(f"[W{wave}] ❌ 생성 파싱 실패 (Fail-Safe Abort) — WAVE {wave} 건너뜀")
                        gen_title = None
                        break
                    gen_title   = result["title"]
                    gen_content = result["content"]
                    q_log(f"[W{wave}] ✅ 생성 완료: '{gen_title[:30]}'")

                    # ── 댓글 타겟 로그 ───────────────────────────────────────
                    _tc_list = result.get("target_comments", [])
                    if _tc_list:
                        for _tc in _tc_list:
                            q_log(
                                f"[W{wave}] 💬 댓글 예약 "
                                f"#{_tc.get('post_no')} → \"{str(_tc.get('comment', ''))[:50]}\""
                            )
                    else:
                        q_log(f"[W{wave}] 💬 댓글 타겟 없음 (AI 판단)")

                    q_preview(gen_title, gen_content, wave, "GENERATED")
                    break

                except RateLimitError:
                    if attempt < 2:
                        backoff = 60 * (2 ** attempt)
                        q_log(f"[W{wave}] ⚠️ Rate Limit (429) — {backoff}초 대기 후 재시도 ({attempt+1}/3)...")
                        _interruptible_sleep(backoff, stop_ev)
                    else:
                        q_log(f"[W{wave}] ❌ Rate Limit 재시도 한도(3회) 초과 — WAVE {wave} 건너뜀")
                        gen_title = None

                except Exception as e:
                    q_log(f"[W{wave}] ❌ 생성 실패: {str(e)[:80]}")
                    gen_title = None
                    break

            if not gen_title or stop_ev.is_set():
                continue

            # ── 계정 큐에서 다음 계정 순서대로 선택 ────────────────────────
            if not _account_queue:
                _account_queue = list(_account_pool)
                random.shuffle(_account_queue)
                q_log("[SWARM] 🔄 계정 큐 소진 — 재충전 + 재셔플 완료")
            _wave_account = _account_queue.pop(0)

            q_log(f"[W{wave}] 🚀 자동 포스팅 시작 → {gallery_type}/{gallery_id}")
            poster = GhostPoster(headless=headless, gallery_type=gallery_type)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                post_result = loop.run_until_complete(
                    poster.auto_post(gallery_id=gallery_id, title=gen_title,
                                     content=gen_content, account=_wave_account,
                                     log_callback=q_log)
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)

            if post_result["success"]:
                q_stat(success=1)
                q_log(f"[W{wave}] 🎉 포스팅 성공! ({post_result['message']})")
                q_preview(gen_title, gen_content, wave, "✅ POSTED")
            else:
                q_stat(fail=1)
                q_log(f"[W{wave}] ❌ 포스팅 실패: {post_result['message']}")
                q_preview(gen_title, gen_content, wave, "❌ FAILED")

            # ── 댓글 자동화 ────────────────────────────────────────────────
            # 포스팅 성공 여부와 무관하게 실행. 계정은 동일 Wave 계정 재사용.
            _comment_elapsed = 0
            if _tc_list and not stop_ev.is_set():
                q_log(f"[W{wave}] 💬 댓글 자동화 시작 — {len(_tc_list)}개 예약")
                for _idx, _tc in enumerate(_tc_list, 1):
                    if stop_ev.is_set():
                        break
                    _post_no = _tc.get("post_no", "")
                    _comment = _tc.get("comment", "")
                    if not _post_no or not _comment:
                        continue

                    q_log(f"[W{wave}] 💬 [{_idx}/{len(_tc_list)}] #{_post_no} 댓글 시도 중...")
                    _c_poster = GhostPoster(headless=headless, gallery_type=gallery_type)
                    _c_loop   = asyncio.new_event_loop()
                    asyncio.set_event_loop(_c_loop)
                    try:
                        _c_result = _c_loop.run_until_complete(
                            _c_poster.auto_comment(
                                gallery_id=gallery_id,
                                post_no=_post_no,
                                comment=_comment,
                                account=_wave_account,
                                log_callback=q_log,
                            )
                        )
                    finally:
                        _c_loop.close()
                        asyncio.set_event_loop(None)

                    if _c_result["success"]:
                        q_log(f"[W{wave}] ✅ 댓글 성공 [{_idx}] #{_post_no}")
                    else:
                        q_log(f"[W{wave}] ❌ 댓글 실패 [{_idx}]: {_c_result['message']}")

                    # 댓글 간 인간다운 딜레이 (마지막 댓글은 Wave 간 딜레이로 흡수)
                    if _idx < len(_tc_list) and not stop_ev.is_set():
                        _c_wait = random.randint(15, 45)
                        q_log(f"[W{wave}] ⏳ 다음 댓글까지 {_c_wait}초 대기...")
                        _interruptible_sleep(_c_wait, stop_ev)
                        _comment_elapsed += _c_wait

            if wave < wave_count and not stop_ev.is_set():
                # 댓글에서 소비된 시간만큼 Wave 간 딜레이에서 차감 (최소 30초 보장)
                _base_wait = random.randint(60, 180)
                wait_sec   = max(30, _base_wait - _comment_elapsed)
                q_log(f"[SWARM] ☕ 다음 WAVE까지 {wait_sec}초 대기...")
                _interruptible_sleep(wait_sec, stop_ev)

        # ── 사이클 완료 후 처리 ───────────────────────────────────────────────
        if stop_ev.is_set() or not infinite:
            break

        # 무한 모드: 다음 사이클 전 긴 쿨타임 (IP 차단 방지)
        _cooldown = random.randint(600, 1800)  # 10~30분 랜덤
        q_log(
            f"[∞] 🌙 사이클 {_cycle} 완료 ({wave_count} WAVES) "
            f"— 다음 사이클까지 {_cooldown // 60}분 {_cooldown % 60}초 대기 "
            f"(🛑 STOP으로 즉시 중단 가능)"
        )
        _interruptible_sleep(_cooldown, stop_ev)
        if stop_ev.is_set():
            break
        q_log(f"[∞] ☀️ 쿨타임 종료 — 사이클 {_cycle + 1} 시작")

    if infinite:
        q_log(f"[∞] ═══ INFINITE SWARM HALTED — 총 {_global_wave} WAVES 완료 ═══")
    else:
        q_log(f"═══════ SWARM COMPLETE — {wave_count} WAVES FIRED ═══════")
    log_q.put({"type": "done"})


def _intel_worker(
    log_q: queue.Queue,
    *,
    api_key: str,
    gallery_id: str,
    gallery_type: str,
    pages: int,
) -> None:
    """백그라운드 스레드: TrendScraper 수집 → GhostBrain.analyze_trend() 분석."""
    from ghost_protocol.scraper import TrendScraper
    from ghost_protocol.brain import GhostBrain, RateLimitError

    def _log(msg: str) -> None:
        log_q.put({"type": "intel_log", "data": msg})

    try:
        brain = GhostBrain(api_key=api_key or None)
    except Exception as e:
        _log(f"❌ Gemini 초기화 실패: {str(e)[:100]}")
        log_q.put({"type": "intel_done"})
        return

    _log(f"🔍 [{gallery_id}] 트렌드 수집 시작 (AJAX 모드, {pages} 페이지)")
    try:
        scraper  = TrendScraper()
        raw_data = scraper.collect_trending(
            gallery_id=gallery_id, gallery_type=gallery_type,
            pages=pages, progress_callback=_log,
        )
    except ImportError as e:
        _log(f"❌ 의존성 오류: {e}")
        log_q.put({"type": "intel_done"})
        return
    except Exception as e:
        _log(f"❌ 수집 실패: {str(e)[:120]}")
        log_q.put({"type": "intel_done"})
        return

    if not raw_data.get("titles"):
        _log("⚠️ 수집된 데이터 없음 — 갤러리 ID / 타입 확인 필요")
        log_q.put({"type": "intel_done"})
        return

    _log("🧠 Gemini 트렌드 분석 중...")
    try:
        result = brain.analyze_trend(raw_data)
        _log("✅ 분석 완료!")
        log_q.put({"type": "intel_result", "data": result})
    except RateLimitError:
        _log("⚠️ Rate Limit (429) — 1분 후 재시도하세요.")
    except Exception as e:
        _log(f"❌ 분석 실패: {str(e)[:120]}")

    log_q.put({"type": "intel_done"})


# ══════════════════════════════════════════════════════════════════════════════
# 배치 생성 워커 — LLM 호출만, 포스팅 없음
# ══════════════════════════════════════════════════════════════════════════════

def _batch_gen_worker(
    log_q: queue.Queue,
    stop_ev: threading.Event,
    *,
    api_key: str,
    topic: str,
    wave_count: int,
    gallery_id: str,
    gallery_type: str,
    tone: str,
    length: str,
    infinite: bool = False,
    auto_refresh: bool = False,
) -> None:
    """백그라운드 스레드: N개 Wave 분량의 대본(제목+본문)을 일괄 사전 생성.
    포스팅은 하지 않는다. 완료 시 batch_done 메시지로 scripts 리스트를 반환.
    infinite=True 면 wave_count를 최대 10으로 제한하여 한 묶음만 생성.
    """

    def q_log(msg: str) -> None:
        log_q.put({"type": "log", "data": msg})

    # Phase 10: 무한 모드는 항상 10개 강제 (fire_clicked에서 이미 보정하지만 이중 방어)
    actual_count = 10 if infinite else wave_count

    try:
        brain = GhostBrain(api_key=api_key or None)
        database.init_db()
    except Exception as e:
        q_log(f"❌ Brain 초기화 실패: {str(e)[:120]}")
        log_q.put({"type": "batch_done", "scripts": []})
        return

    # ── 사이클 메모리 로드 ────────────────────────────────────────────────────
    # 무한 반복 시 화제 고착화·감성 극단화·어휘 수렴을 방지하는 상태 지속 메모리.
    # cycle_memory.json 파일로 사이클 간 영속 저장.
    _mem              = _cm.load()
    _mem_cycle        = _cm.increment_cycle(_mem)
    _banned_topics    = _cm.get_banned_topics(_mem)
    _banned_starts    = _cm.get_banned_starts(_mem)
    _sentiment_score  = _cm.get_sentiment_score(_mem)
    _current_hour     = datetime.datetime.now().hour
    _batch_first_words: list[str] = []   # 어휘 엔트로피 추적용 first_word 수집

    # 금지 화제 주입 — TTL 초과 키워드를 topic에 경고로 삽입
    if _banned_topics:
        _ban_str = " / ".join(_banned_topics)
        topic = (
            topic
            + f"\n[⛔ 반복 화제 금지 — {_cm.TOPIC_TTL_BAN}사이클 이상 연속 도배 감지, 완전히 다른 소재 발굴 필수]: {_ban_str}"
        )
        q_log(f"[CYCLE-MEM] 🔄 사이클 {_mem_cycle} | 반복 화제 금지 {len(_banned_topics)}개: {_ban_str}")

    # 어휘 자동 금지어 주입 — first_word 수렴 감지 시 차단
    if _banned_starts:
        _vocab_str = " / ".join(_banned_starts)
        topic = (
            topic
            + f"\n[⛔ 본문 첫 어절 자동 금지 (반복 과다 탐지)]: {_vocab_str}"
        )
        q_log(f"[CYCLE-MEM] 📝 어휘 수렴 금지어 {len(_banned_starts)}개: {_vocab_str}")

    if _sentiment_score <= _cm.DRIFT_THRESHOLD:
        q_log(f"[CYCLE-MEM] 🌡️ 감성 drift 감지 (score={_sentiment_score}) — HOT 상한 절반, mutant 최대 적용")

    _cm.save(_mem)   # cycle_count 증가 즉시 저장

    # ── 봇 아이덴티티 풀 로드 ────────────────────────────────────────────────
    # 무한 반복 시 봇 발화 성향이 사이클마다 동일해지는 문제를 방지.
    # 25% 확률로 wave별 발화 정체성(아이덴티티)을 topic에 오버레이.
    _bot_identities: list[dict] = pm.load_json("bot_identities.json") or []

    # ── 세계관 자동 갱신 (무한 모드 전용: 직전 배치 발행 직후 최신 갤러리 반영) ──
    # auto_refresh=True → 1페이지 재스캔 + analyze_trend() 실행.
    # 성공 시: topic 로컬 변수를 새 ai_analysis로 교체 → 이 배치 전체에 적용.
    # 실패 시: 기존 topic 그대로 유지 (silent fallback).
    if auto_refresh and not stop_ev.is_set():
        q_log("[🔄 AUTO-REFRESH] 갤러리 재스캔 + 세계관 갱신 중...")
        try:
            from ghost_protocol.scraper import TrendScraper as _AR_TS
            # 외부 자극 강제 주입: 3사이클마다 2페이지 스크래핑 → 더 넓은 외부 데이터 흡수
            _scrape_pages = 2 if (_mem_cycle % 3 == 0) else 1
            if _scrape_pages > 1:
                q_log(f"[AUTO-REFRESH] 🌐 사이클 {_mem_cycle} — 외부 자극 강화 ({_scrape_pages}페이지 스크래핑)")
            _ar_raw = _AR_TS().collect_trending(
                gallery_id=gallery_id, gallery_type=gallery_type, pages=_scrape_pages,
            )
            if _ar_raw.get("titles"):
                # ── Gemini 분석 타임아웃 래퍼 ─────────────────────────────────────
                # brain.analyze_trend()는 google.genai SDK를 동기 호출하며,
                # 네트워크 지연 / Rate Limit 무응답 시 무한 대기(Hang)를 유발한다.
                # → ThreadPoolExecutor + result(timeout=25)로 25초 이내로 제한.
                # 타임아웃 초과 시 orphan 스레드가 남지만 워커는 즉시 폴백 진행.
                _ar_result = None
                try:
                    with _cf.ThreadPoolExecutor(max_workers=1) as _ar_pool:
                        _ar_fut = _ar_pool.submit(brain.analyze_trend, _ar_raw)
                        _ar_result = _ar_fut.result(timeout=25)
                except _cf.TimeoutError:
                    q_log("[AUTO-REFRESH] ⚠️ AI 분석 타임아웃 (25s) — 기존 토픽 유지")
                except Exception as _ar_inner_e:
                    q_log(f"[AUTO-REFRESH] ⚠️ AI 분석 실패: {str(_ar_inner_e)[:80]}")

                if _ar_result:
                    _fresh_ai      = (_ar_result.get("ai_analysis") or "").strip()
                    _fresh_summary = (_ar_result.get("summary") or "").strip()
                    _fresh_topic   = (
                        _fresh_ai
                        + ("\n씨앗 떡밥: " + _fresh_summary if _fresh_summary else "")
                    ).strip()
                    if _fresh_topic:
                        topic = _fresh_topic   # 이 배치의 $topic 갱신
                        # 금지 화제·어휘 재주입 (갱신된 topic에도 유지)
                        if _banned_topics:
                            topic += f"\n[⛔ 반복 화제 금지]: {' / '.join(_banned_topics)}"
                        if _banned_starts:
                            topic += f"\n[⛔ 본문 첫 어절 금지]: {' / '.join(_banned_starts)}"
                        log_q.put({"type": "context_updated",
                                   "topic": topic, "intel": _ar_result})
                        q_log("[AUTO-REFRESH] ✅ 세계관 갱신 완료 — 최신 브리핑으로 대본 생성")
                    else:
                        q_log("[AUTO-REFRESH] ⚠️ 분석 비어있음 — 기존 토픽 유지")

                    # ── 사이클 메모리 갱신 (hot_topics TTL + sentiment 진자) ──────
                    _cm.update_topic_ttl(_mem, _ar_result.get("hot_topics", []))
                    _new_sentiment = _cm.update_sentiment(_mem, _ar_result.get("sentiment", ""))
                    _new_banned    = _cm.get_banned_topics(_mem)
                    _cm.save(_mem)
                    q_log(
                        f"[CYCLE-MEM] 💾 TTL 갱신 완료 | "
                        f"금지 화제={_new_banned} | 감성점수={_new_sentiment}"
                    )
            else:
                q_log("[AUTO-REFRESH] ⚠️ 수집 데이터 없음 — 기존 토픽 유지")
        except Exception as _ar_e:
            q_log(f"[AUTO-REFRESH] ⚠️ 갱신 실패, 기존 토픽으로 폴백: {str(_ar_e)[:80]}")

    # ── 댓글 타겟 풀 수집 + 기존 댓글 프리패치 (배치 시작 시 1회) ────────────
    # 봇 글 제외 최대 15개 수집 → 기존 댓글 AJAX 프리패치 → enriched_pool 구성.
    # 매 Wave마다 이 풀에서 랜덤 서브셋 5개를 뽑아 군중 쏠림 현상 방지.
    # Phase 8: 수집 전 로그 출력 + 30초 타임아웃 래퍼 → 블라인드 행 방지.
    _enriched_pool: list[dict] = []
    q_log("[BATCH] 🔍 게시글 목록 및 댓글 맥락 수집 중... (최대 30초)")
    try:
        def _collect_pool() -> list[dict]:
            from ghost_protocol.scraper import TrendScraper as _TS
            _ts = _TS()
            _raw_list = _ts.fetch_post_list(gallery_id, gallery_type, page=1)
            _candidates = [p for p in _raw_list if not p.get("is_bot")][:15]
            _pool: list[dict] = []
            for _c in _candidates:
                _cmts: list[str] = []
                try:
                    _cmts = _ts.fetch_comments_ajax(
                        gallery_id, _c["post_no"], gallery_type
                    )[:5]
                except Exception:
                    pass
                _pool.append({
                    "post_no":           _c["post_no"],
                    "title":             _c["title"],
                    "existing_comments": _cmts,
                })
            return _pool

        _enriched_pool = _timed(_collect_pool, _timeout=30.0)
        q_log(f"[BATCH] 📋 댓글 타겟 풀: {len(_enriched_pool)}개 (맥락 프리패치 완료)")
    except _cf.TimeoutError:
        q_log("[BATCH] ⚠️ 댓글 타겟 수집 타임아웃 (30s) — 빈 풀로 계속 진행")
    except Exception as _te:
        q_log(f"[BATCH] ⚠️ 댓글 타겟 수집 실패 (계속): {str(_te)[:80]}")

    # ── 온도 밸런싱 라인업 빌드 ─────────────────────────────────────────
    # HOT ≤ 30% / NEUTRAL ≥ 20% / mutant 2~3개 보장 / 연속 HOT 3회 이상 불가.
    # sentiment_score: 감성 drift 보정 (≤-2 → HOT 상한 절반, mutant 최대)
    # hour: 시간대 리듬 기반 WARM pool 가중치 조정
    _wave_lineup = _build_balanced_lineup(
        actual_count,
        sentiment_score=_sentiment_score,
        hour=_current_hour,
    )

    scripts: list[dict] = []

    for wave in range(1, actual_count + 1):
        if stop_ev.is_set():
            q_log("[BATCH] 🛑 중단 요청 — 대본 생성 중단")
            break

        q_log(f"[BATCH] 🎬 대본 {wave}/{actual_count} 생성 중...")
        log_q.put({"type": "batch_progress", "wave": wave, "total": actual_count})

        _persona   = _wave_lineup[wave - 1]
        _wave_tone = _persona["key"]
        q_log(f"[BATCH] 🎭 [{wave}] 페르소나: {_persona['name']} ({_wave_tone})")

        # ── 봇 아이덴티티 오버레이 (25% 확률) ──────────────────────────────
        # 특정 발화 정체성을 topic에 추가하여 사이클 간 언어 다양성 보장.
        # trigger_keywords 매칭 우선, 없으면 랜덤 선택.
        _wave_topic = topic
        if _bot_identities and random.random() < 0.25:
            _matched_ids = [
                bid for bid in _bot_identities
                if any(kw in topic for kw in bid.get("trigger_keywords", []))
            ]
            _chosen_id = random.choice(_matched_ids if _matched_ids else _bot_identities)
            _wave_topic = (
                topic
                + f"\n[🎭 이 글의 발화 정체성: '{_chosen_id['name']}' ({_chosen_id['bias']}) — {_chosen_id['signature_style']}]"
            )
            q_log(f"[BATCH] 🪪 [{wave}] 봇 아이덴티티 적용: {_chosen_id['name']}")

        gen_title: str | None = None
        gen_content: str = ""
        _tc_list: list[dict] = []

        for attempt in range(3):
            if stop_ev.is_set():
                break
            try:
                # 매 Wave마다 타겟 풀에서 랜덤 서브셋 선택 — 군중 쏠림 방지
                _wave_targets = (
                    random.sample(_enriched_pool, min(5, len(_enriched_pool)))
                    if _enriched_pool else None
                )
                # Phase 8: generate_post()에 40초 타임아웃 적용 — 무한 대기 차단
                result = _timed(
                    brain.generate_post,
                    _timeout=40.0,
                    topic=_wave_topic,
                    gallery_id=gallery_id,
                    tone=_wave_tone,
                    context_hours=None,
                    length=length,
                    recent_posts=_wave_targets,
                )
                if result.get("_parse_error") or not result.get("title") or not result.get("content"):
                    q_log(f"[BATCH] ❌ [{wave}] 파싱 실패 — 건너뜀")
                    break
                gen_title   = result["title"]
                gen_content = result["content"]
                _tc_list    = result.get("target_comments", [])
                q_log(f"[BATCH] ✅ [{wave}] 생성 완료: '{gen_title[:30]}'")
                # 어휘 엔트로피 추적: 본문 첫 어절 수집
                _fw = gen_content.strip().split()[0] if gen_content.strip() else ""
                if _fw:
                    _batch_first_words.append(_fw)
                break

            except _cf.TimeoutError:
                q_log(f"[BATCH] ⏱️ [{wave}] 생성 타임아웃 (40s) — 이 대본 건너뜀")
                break  # 부분 실패 허용: 이 Wave만 스킵, 다음 Wave 계속
            except RateLimitError:
                if attempt < 2:
                    backoff = 60 * (2 ** attempt)
                    q_log(f"[BATCH] ⚠️ [{wave}] Rate Limit — {backoff}초 대기 ({attempt+1}/3)...")
                    _interruptible_sleep(backoff, stop_ev)
                else:
                    q_log(f"[BATCH] ❌ [{wave}] Rate Limit 재시도 한도 초과")
            except Exception as e:
                q_log(f"[BATCH] ❌ [{wave}] 생성 오류: {str(e)[:80]}")
                break

        scripts.append({
            "wave":             wave,
            "persona_name":     _persona["name"],
            "tone":             _wave_tone,
            "title":            gen_title or "",
            "content":          gen_content,
            "target_comments":  _tc_list,
            "_failed":          gen_title is None,
        })

    ok_count = sum(1 for s in scripts if not s.get("_failed"))
    q_log(f"[BATCH] 🎬 대본 생성 완료 — 성공 {ok_count}/{len(scripts)}개")

    # ── 어휘 엔트로피 최종 저장 ─────────────────────────────────────────────
    # 이 배치에서 수집된 first_words를 슬라이딩 윈도우에 추가.
    # 다음 사이클에서 get_banned_starts()로 읽어 자동 금지어로 주입.
    if _batch_first_words:
        _new_banned_starts = _cm.update_vocab(_mem, _batch_first_words)
        _cm.save(_mem)
        if _new_banned_starts:
            q_log(
                f"[CYCLE-MEM] 📊 어휘 수렴 감지 — 다음 사이클 자동 금지어: {_new_banned_starts}"
            )

    log_q.put({"type": "batch_done", "scripts": scripts})


# ══════════════════════════════════════════════════════════════════════════════
# 연재 실행 워커 — 사전 생성된 대본을 순차 발행
# ══════════════════════════════════════════════════════════════════════════════

def _post_exec_worker(
    log_q: queue.Queue,
    stop_ev: threading.Event,
    *,
    scripts: list[dict],
    gallery_id: str,
    gallery_type: str,
    headless: bool,
) -> None:
    """백그라운드 스레드: 검수 완료된 대본을 Wave 간 쿨타임에 맞춰 순차 발행.
    메시지 포맷은 기존 _swarm_worker와 동일 (log / preview / stat / done).
    """

    def q_log(msg: str) -> None:
        log_q.put({"type": "log", "data": msg})

    def q_preview(title: str, content: str, wave: int, status: str) -> None:
        log_q.put({"type": "preview", "title": title, "content": content,
                   "wave": wave, "status": status})

    def q_stat(success: int = 0, fail: int = 0) -> None:
        log_q.put({"type": "stat", "success": success, "fail": fail})

    try:
        _account_pool = load_accounts()
    except (FileNotFoundError, ValueError) as _ae:
        q_log(f"❌ 계정 로드 실패 — 연재 중단: {str(_ae)[:120]}")
        log_q.put({"type": "done"})
        return

    _account_queue: list[dict] = list(_account_pool)
    valid_scripts = [s for s in scripts if not s.get("_failed") and s.get("title")]

    if not valid_scripts:
        q_log("[EXEC] ⚠️ 발행 가능한 대본이 없습니다.")
        log_q.put({"type": "done"})
        return

    q_log(f"[EXEC] 📬 연재 시작 — {len(valid_scripts)}개 대본 발행 예정")

    for i, script in enumerate(valid_scripts):
        if stop_ev.is_set():
            q_log("[EXEC] 🛑 중단 요청 — 연재 중단")
            break

        wave        = script["wave"]
        gen_title   = script["title"]
        gen_content = script["content"]
        _tc_list    = script.get("target_comments", [])

        q_log(f"═══════ WAVE {wave} ({i + 1}/{len(valid_scripts)}) ═══════")
        q_log(f"[W{wave}] 🚀 포스팅 시작 → {gallery_type}/{gallery_id}")
        q_preview(gen_title, gen_content, wave, "POSTING...")

        # 계정 큐 순환
        if not _account_queue:
            _account_queue = list(_account_pool)
            random.shuffle(_account_queue)
            q_log("[EXEC] 🔄 계정 큐 재충전")
        _wave_account = _account_queue.pop(0)

        poster = GhostPoster(headless=headless, gallery_type=gallery_type)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            post_result = loop.run_until_complete(
                poster.auto_post(gallery_id=gallery_id, title=gen_title,
                                 content=gen_content, account=_wave_account,
                                 log_callback=q_log)
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        if post_result["success"]:
            q_stat(success=1)
            q_log(f"[W{wave}] 🎉 포스팅 성공! ({post_result['message']})")
            q_preview(gen_title, gen_content, wave, "✅ POSTED")
        else:
            q_stat(fail=1)
            q_log(f"[W{wave}] ❌ 포스팅 실패: {post_result['message']}")
            q_preview(gen_title, gen_content, wave, "❌ FAILED")

        # 댓글 자동화
        _comment_elapsed = 0
        if _tc_list and not stop_ev.is_set():
            q_log(f"[W{wave}] 💬 댓글 자동화 — {len(_tc_list)}개 예약")
            for _idx, _tc in enumerate(_tc_list, 1):
                if stop_ev.is_set():
                    break
                _post_no = _tc.get("post_no", "")
                _comment = _tc.get("comment", "")
                if not _post_no or not _comment:
                    continue

                q_log(f"[W{wave}] 💬 [{_idx}/{len(_tc_list)}] #{_post_no} 댓글 시도 중...")
                _c_poster = GhostPoster(headless=headless, gallery_type=gallery_type)
                _c_loop   = asyncio.new_event_loop()
                asyncio.set_event_loop(_c_loop)
                try:
                    _c_result = _c_loop.run_until_complete(
                        _c_poster.auto_comment(
                            gallery_id=gallery_id,
                            post_no=_post_no,
                            comment=_comment,
                            account=_wave_account,
                            log_callback=q_log,
                        )
                    )
                finally:
                    _c_loop.close()
                    asyncio.set_event_loop(None)

                if _c_result["success"]:
                    q_log(f"[W{wave}] ✅ 댓글 성공 [{_idx}]")
                else:
                    q_log(f"[W{wave}] ❌ 댓글 실패 [{_idx}]: {_c_result['message']}")

                if _idx < len(_tc_list) and not stop_ev.is_set():
                    _c_wait = random.randint(15, 45)
                    _interruptible_sleep(_c_wait, stop_ev)
                    _comment_elapsed += _c_wait

        # Wave 간 쿨타임
        if i < len(valid_scripts) - 1 and not stop_ev.is_set():
            _base_wait = random.randint(60, 180)
            wait_sec   = max(30, _base_wait - _comment_elapsed)
            q_log(f"[EXEC] ☕ 다음 WAVE까지 {wait_sec}초 대기...")
            _interruptible_sleep(wait_sec, stop_ev)

    q_log(f"═══════ EXECUTION COMPLETE — {len(valid_scripts)} WAVES FIRED ═══════")
    log_q.put({"type": "done"})


# ══════════════════════════════════════════════════════════════════════════════
# 헬퍼: 무한 모드 자동 포스팅 워커 시작 (검수 게이트 우회)
# ══════════════════════════════════════════════════════════════════════════════


def _auto_launch_swarm(ss: "st.session_state", scripts: list) -> None:  # type: ignore[name-defined]
    """무한 모드 전용: 검수 게이트 없이 포스팅 워커를 즉시 시작.

    _review_board_fragment의 '✅ 대본 최종 승인' 버튼 핸들러 로직을 DRY하게 추출.
    유효 대본(not _failed)이 0개면 즉시 다음 배치 사이클로 넘어가 실패 루프를 방지.
    """
    valid = [s for s in scripts if not s.get("_failed")]
    if not valid:
        # 전량 생성 실패 → 포스팅 없이 다음 사이클 즉시 재개
        ss.swarm_log.append("[∞] ⚠️ 유효 대본 0개 — 포스팅 건너뛰고 다음 사이클 시작")
        _start_next_batch(ss)
        return

    _post_q:  queue.Queue     = queue.Queue()
    _post_ev: threading.Event = threading.Event()

    ss.review_ready          = False
    ss.swarm_running         = True
    ss.swarm_queue           = _post_q
    ss.swarm_stop_event      = _post_ev
    ss.swarm_preview_title   = ""
    ss.swarm_preview_content = ""
    ss.swarm_wave_total      = len(valid)
    ss.swarm_wave_current    = 0
    ss.last_fired            = True

    _cfg = ss.get("_batch_gen_config", {})
    threading.Thread(
        target=_post_exec_worker,
        kwargs={
            "log_q":        _post_q,
            "stop_ev":      _post_ev,
            "scripts":      scripts,
            "gallery_id":   _cfg.get("gallery_id", ""),
            "gallery_type": _cfg.get("gallery_type", "mgallery"),
            "headless":     _cfg.get("headless", True),
        },
        daemon=True,
    ).start()


# 헬퍼: 다음 배치 생성 시작 (무한 모드 자동 재배치용)
# ══════════════════════════════════════════════════════════════════════════════


# Phase 11: _batch_gen_worker가 받는 파라미터 화이트리스트.
# _batch_gen_config는 _post_exec_worker용 'headless' 등 여분 키를 포함하므로
# {**cfg} 언팩 방식은 새 키가 추가될 때마다 TypeError → daemon 스레드 즉사를 유발하는
# 취약 패턴이다. 명시적 허용 키 집합으로 필터링하여 미래 config 확장에도 안전하게 보호.
_BATCH_GEN_PARAMS: frozenset = frozenset({
    "api_key", "topic", "wave_count", "gallery_id",
    "gallery_type", "tone", "length", "infinite",
})


def _start_next_batch(ss: "st.session_state") -> None:  # type: ignore[name-defined]
    """저장된 _batch_gen_config를 이용해 다음 배치 생성 워커를 즉시 시작.

    Phase 11 버그픽스:
      _batch_gen_config의 'headless' 키가 {**cfg} 언팩으로 _batch_gen_worker에
      그대로 전달되어 TypeError → daemon 스레드 즉사 → 무한 루프 단절 버그 수정.
      _BATCH_GEN_PARAMS 화이트리스트로 허용 키만 필터링하여 전달.
    """
    cfg = ss.get("_batch_gen_config", {})
    if not cfg:
        return
    _bgq  = queue.Queue()
    _bgev = threading.Event()
    ss.batch_generating     = True
    ss.batch_gen_queue      = _bgq
    ss.batch_gen_stop_event = _bgev
    # Phase 8: 로그 초기화 대신 사이클 구분선 추가 — 이전 사이클 기록 보존
    _cycle_num = getattr(ss, "_batch_cycle_count", 0) + 1
    ss._batch_cycle_count   = _cycle_num
    _prev_log = list(getattr(ss, "swarm_log", []))[-200:]
    _sep = f"══════════ 🔄 CYCLE {_cycle_num} 시작 (AUTO-REFRESH) ══════════"
    ss.swarm_log            = _prev_log + [_sep]
    ss.swarm_wave_current   = 0
    ss.swarm_wave_total     = cfg.get("wave_count", 10)
    # Phase 11 핵심 픽스: headless 등 worker 미지원 키 차단 — 화이트리스트 필터
    _worker_cfg = {k: v for k, v in cfg.items() if k in _BATCH_GEN_PARAMS}
    threading.Thread(
        target=_batch_gen_worker,
        kwargs={**_worker_cfg, "log_q": _bgq, "stop_ev": _bgev, "auto_refresh": True},
        daemon=True,
    ).start()


# ══════════════════════════════════════════════
# Terminal HTML 렌더러
# ══════════════════════════════════════════════
def render_terminal(logs: list, height_px: int = 400) -> str:
    parts = []
    for line in reversed(logs[-200:]):
        if any(k in line for k in ("═══", "WAVE", "SWARM")):
            parts.append(f'<div><span class="t-wave">{_html.escape(line)}</span></div>')
        elif any(k in line for k in ("✅", "🎉", "성공", "COMPLETE", "OK")):
            parts.append(f'<div><span class="t-ok">{_html.escape(line)}</span></div>')
        elif any(k in line for k in ("❌", "ERROR", "FAIL", "실패", "[ERROR]")):
            parts.append(f'<div><span class="t-err">{_html.escape(line)}</span></div>')
        elif any(k in line for k in ("🧠", "🚀", "🔑", "⌨️", "📄", "🌐", "🖱️", "🖼️")):
            parts.append(f'<div><span class="t-info">{_html.escape(line)}</span></div>')
        elif any(k in line for k in ("☕", "⏳", "⚠️", "🛡️", "🕶️")):
            parts.append(f'<div><span class="t-warn">{_html.escape(line)}</span></div>')
        else:
            parts.append(f'<div>{_html.escape(line)}</div>')
    body = "\n".join(parts) if parts else (
        '<div style="color:#30363D;font-style:italic">// awaiting launch sequence...</div>'
    )
    return f'<div class="terminal" style="height:{height_px}px;">{body}</div>'


# ══════════════════════════════════════════════
# 대본 Plaintext 포맷터 (검수 보드 복사용)
# ══════════════════════════════════════════════
def _format_scripts_for_copy(scripts: list[dict]) -> str:
    """생성된 대본 목록을 가독성 좋은 평문(Plaintext)으로 변환.

    Review Board의 '전체 대본 복사' 기능에서 st.code()에 주입된다.
    """
    ts    = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 60,
        "GHOST PROTOCOL — 대본 전체 스크립트",
        f"생성 시각: {ts}",
        f"총 {len(scripts)}개 WAVE",
        "=" * 60,
    ]
    for s in scripts:
        lines.append("")
        wave    = s.get("wave", "?")
        persona = s.get("persona_name", "")
        tone_k  = s.get("tone", "")
        lines.append(f"▌ WAVE {wave}  [{persona} / {tone_k}]")
        if s.get("_failed"):
            lines.append("  [생성 실패 — 연재 시 건너뜀]")
        else:
            lines.append(f"  제목: {s.get('title', '')}")
            content_lines = s.get("content", "").splitlines()
            for i, cl in enumerate(content_lines):
                prefix = "  본문: " if i == 0 else "        "
                lines.append(f"{prefix}{cl}")
            for tc in s.get("target_comments", []):
                lines.append(
                    f"  댓글 → #{tc.get('post_no','?')}: {tc.get('comment', '')}"
                )
        lines.append("-" * 40)
    return "\n".join(lines)


# ══════════════════════════════════════════════
# Plotly 차트 빌더 (캐시 로직은 호출부에서 관리)
# ══════════════════════════════════════════════
def _build_intel_fig(ir: dict) -> "go.Figure | None":
    """intel_result dict에서 Plotly 키워드 빈도 차트를 생성한다."""
    kw_all    = ir.get("top_keywords", [])[:30]
    kw_counts = ir.get("keyword_counts", {})
    if not kw_all:
        return None
    if not kw_counts:
        kw_counts = {w: len(kw_all) - i for i, w in enumerate(kw_all)}
    n        = min(20, len(kw_all))
    words    = kw_all[:n]
    vals     = [kw_counts.get(w, 1) for w in words]
    words_r  = words[::-1]
    vals_r   = vals[::-1]
    fig = go.Figure(go.Bar(
        x=vals_r, y=words_r, orientation="h",
        marker=dict(color=vals_r,
                    colorscale=[[0, "#1C3A50"], [0.45, "#006688"], [1.0, "#00F0FF"]],
                    showscale=False, line=dict(width=0)),
        hovertemplate="<b>%{y}</b><br>빈도: %{x}회<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#141820", plot_bgcolor="#141820",
        height=max(320, n * 22), margin=dict(l=0, r=16, t=36, b=8),
        title=dict(text="📊 KEYWORD FREQUENCY  —  TOP 20",
                   font=dict(size=10, color="#444444", family="monospace"), x=0),
        xaxis=dict(gridcolor="rgba(255,255,255,0.05)",
                   tickfont=dict(size=9, color="#555555", family="monospace"),
                   title=None, zeroline=False),
        yaxis=dict(tickfont=dict(size=11, color="#BBBBBB"), title=None, automargin=True),
        hoverlabel=dict(bgcolor="#1A2030", font_size=12, font_family="monospace",
                        bordercolor="rgba(0,240,255,0.3)"),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# DB CSV 내보내기 — @st.cache_data 래퍼 (module level 필수)
# ttl=300: 5분 캐시 → 재렌더 시 재연산 없음 / 신선도 균형
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300, show_spinner=False)
def _cached_posts_csv(gallery_id: str) -> tuple[bytes, int]:
    return database.build_posts_csv_bytes(gallery_id)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_comments_csv(gallery_id: str) -> tuple[bytes, int]:
    return database.build_comments_csv_bytes(gallery_id)


# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — INTEL 결과 렌더링 + 폴링
# 이 fragment만 0.5초마다 재실행 — 전체 페이지 flickering 없음
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _intel_results_fragment() -> None:
    """INTEL 결과 렌더 + 워커 폴링 fragment.

    • intel_running=True 동안 queue 드레인 → session_state 갱신 → fragment 재실행
    • 완료(intel_done) 수신 시 scope='app' 전체 재실행 → 버튼 재활성화
    • Plotly fig는 intel_result 해시가 바뀔 때만 재생성 (flickering 방지)
    """
    ss = st.session_state

    # ── INTEL Queue 드레인 ──────────────────────────────────────────────
    _intel_done = False
    if ss.get("intel_running") and ss.get("intel_queue") is not None:
        iq: queue.Queue = ss.intel_queue
        while True:
            try:
                msg = iq.get_nowait()
            except queue.Empty:
                break

            if msg["type"] == "intel_log":
                ss.intel_log.append(msg["data"])

            elif msg["type"] == "intel_result":
                _data = msg["data"]
                ss.intel_result = _data
                _ck = f"{ss.get('intel_gallery_id', '')}::{_TYPE_MAP.get(ss.get('intel_type_label', '마이너 (mgallery)'), 'mgallery')}"
                ss.intel_cache[_ck] = {"result": _data, "ts": time.time()}
                ss["_intel_fig_key"] = None  # 캐시 무효화 → 다음 렌더에서 재생성

            elif msg["type"] == "intel_done":
                ss.intel_running = False
                ss.intel_queue   = None
                _intel_done = True
                # 분석 성공 시 갤러리 히스토리 저장 (파일 기반, 비파괴적)
                if ss.intel_result:
                    _history_save(
                        ss.get("intel_gallery_id", ""),
                        ss.get("intel_type_label", "마이너 (mgallery)"),
                    )

    # ── 표시할 결과 결정 (live result > cache) ─────────────────────────
    _ir = ss.intel_result
    if _ir is None and not ss.get("intel_running"):
        _ck = f"{ss.get('intel_gallery_id', '')}::{_TYPE_MAP.get(ss.get('intel_type_label', '마이너 (mgallery)'), 'mgallery')}"
        _cached = ss.intel_cache.get(_ck)
        if _cached and (time.time() - _cached.get("ts", 0)) < _INTEL_CACHE_TTL:
            _ir = _cached["result"]

    # ── 결과 렌더링 ─────────────────────────────────────────────────────
    if _ir:
        _SENTIMENT_CLS = {
            "패닉": "panic", "공포": "panic", "적대적": "hostile",
            "분노": "hostile", "공격": "hostile", "조롱": "mock",
            "냉소": "mock", "비꼬": "mock", "우호적": "friendly", "긍정": "friendly",
        }
        _sent_raw = _ir.get("sentiment", "알 수 없음")
        _sent_cls = "intel-sentiment-neutral"
        for kw, cls in _SENTIMENT_CLS.items():
            if kw in _sent_raw:
                _sent_cls = f"intel-sentiment-{cls}"
                break

        _hot_chips  = "".join(f'<span class="intel-chip-hot">{_html.escape(t)}</span>'  for t in _ir.get("hot_topics", []))
        _meme_chips = "".join(f'<span class="intel-chip-meme">{_html.escape(m)}</span>' for m in _ir.get("memes", []))
        _kw_chips   = "".join(f'<span class="intel-chip-kw">{_html.escape(w)}</span>'   for w in _ir.get("top_keywords", [])[:15])
        _stats_d    = _ir.get("stats", {})
        _stat_pills = (
            f'<span class="intel-stat-pill">제목 <span>{_stats_d.get("titles_count", 0)}</span>개</span>'
            f'<span class="intel-stat-pill">댓글 <span>{_stats_d.get("comments_count", 0)}</span>개</span>'
            f'<span class="intel-stat-pill">키워드 <span>{_stats_d.get("keywords_found", 0)}</span>개</span>'
        )

        # ── AI OCCUPATION RATE 대시보드 ─────────────────────────────────────
        # DB(is_ai=1) 기준으로 현재 스캔 게시글 중 봇 글 수 계산.
        # Ledger 기반 ai_post_count는 ledger가 비어 있으면 0이 되므로,
        # poster.py가 mark_ai_post()로 직접 기록한 DB 값을 우선 사용한다.
        _intel_gid = ss.get("intel_gallery_id", "")
        _raw_posts_scan = _ir.get("raw_posts", [])
        try:
            _ai_nos_db: set[str] = database.get_ai_post_nos(_intel_gid) if _intel_gid else set()
        except Exception:
            _ai_nos_db = set()
        # 현재 스캔 목록 안에서 DB 봇 + ledger 봇 합산 (중복 제거)
        _ai_cnt_db = sum(
            1 for p in _raw_posts_scan
            if p.get("is_bot") or str(p.get("post_no", "")) in _ai_nos_db
        )
        _ai_cnt    = max(_ai_cnt_db, int(_stats_d.get("ai_post_count", 0)))
        _total_cnt = max(len(_raw_posts_scan), int(_stats_d.get("total_post_count", 0)))
        _human_cnt = max(0, _total_cnt - _ai_cnt)

        if _total_cnt > 0:
            _ai_pct    = min(100.0, _ai_cnt / _total_cnt * 100)
            _human_pct = 100.0 - _ai_pct
            _bar_w     = f"{_ai_pct:.1f}%"
            _pct_lbl   = f"{_ai_pct:.1f}%"
            _ratio_lbl = f"{_ai_cnt} / {_total_cnt}개"
        else:
            _ai_pct    = 0.0
            _human_pct = 100.0
            _bar_w     = "0%"
            _pct_lbl   = "—"
            _ratio_lbl = "데이터 없음"

        # 점유율에 따른 색상 3단계: 위협(≥50%) / 경계(≥20%) / 안전(<20%)
        _bar_clr = (
            "linear-gradient(90deg,#FF2020,#FF4B4B)"    if _ai_pct >= 50
            else "linear-gradient(90deg,#FF8C00,#FFBF00)" if _ai_pct >= 20
            else "linear-gradient(90deg,#00C2A0,#00F0FF)"
        )
        _pct_color = (
            "#FF4B4B" if _ai_pct >= 50
            else "#FFBF00" if _ai_pct >= 20
            else "#00F0FF"
        )

        st.markdown(
            f'<div style="background:#0D1117;border:1px solid rgba(255,75,75,0.30);'
            f'border-radius:18px;padding:20px 28px;margin-bottom:16px;">'
            f'  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
            f'    <span style="color:#FF4B4B;font-size:0.60rem;font-weight:700;'
            f'      letter-spacing:3px;text-transform:uppercase">⚡ AI OCCUPATION RATE</span>'
            f'    <span style="color:#333;font-size:0.60rem;font-family:monospace">'
            f'      {_html.escape(ss.get("intel_gallery_id",""))}'
            f'    </span>'
            f'  </div>'
            f'  <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:14px">'
            f'    <span style="font-size:2.8rem;font-weight:900;color:{_pct_color};'
            f'      font-family:monospace;line-height:1;letter-spacing:-1px">'
            f'      {_html.escape(_pct_lbl)}'
            f'    </span>'
            f'    <span style="color:#555;font-size:0.82rem">{_html.escape(_ratio_lbl)}</span>'
            f'  </div>'
            f'  <div style="background:rgba(255,255,255,0.06);border-radius:99px;'
            f'    height:10px;overflow:hidden;margin-bottom:10px">'
            f'    <div style="width:{_bar_w};height:100%;background:{_bar_clr};'
            f'      border-radius:99px"></div>'
            f'  </div>'
            f'  <div style="display:flex;justify-content:space-between">'
            f'    <span style="color:#00C2A0;font-size:0.72rem">'
            f'      🧑 HUMAN &nbsp;{_human_cnt}개 &nbsp;({_human_pct:.1f}%)'
            f'    </span>'
            f'    <span style="color:{_pct_color};font-size:0.72rem">'
            f'      🤖 BOT &nbsp;{_ai_cnt}개 &nbsp;({_ai_pct:.1f}%)'
            f'    </span>'
            f'  </div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        col_brief, col_chart = st.columns([2, 1], gap="large")

        with col_brief:
            st.markdown(
                f'<div class="intel-card">'
                f'  <div class="intel-header">'
                f'    <span class="intel-title">📡 INTEL BRIEFING</span>'
                f'    <span class="intel-gallery-badge">{_html.escape(ss.get("intel_gallery_id",""))}</span>'
                f'  </div>'
                f'  <div class="intel-section-label">OVERALL SENTIMENT</div>'
                f'  <div class="intel-sentiment {_sent_cls}">{_html.escape(_sent_raw)}</div>'
                f'  <div class="intel-section-label">🔥 HOT TOPICS</div>'
                f'  <div class="intel-chips">{_hot_chips}</div>'
                f'  <div class="intel-section-label">💬 TRENDING MEMES</div>'
                f'  <div class="intel-chips">{_meme_chips if _meme_chips else "<span style=\"color:#333;font-size:0.72rem\">감지된 밈 없음</span>"}</div>'
                f'  <div class="intel-section-label" style="margin-top:14px">🔑 TOP KEYWORDS</div>'
                f'  <div class="intel-chips">{_kw_chips}</div>'
                f'  <div class="intel-stats">{_stat_pills}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

            _summary_text    = _ir.get("summary", "").strip()
            _ai_analysis_text = _ir.get("ai_analysis", "").strip()
            if _summary_text or _ai_analysis_text:
                _sb = _html.escape(_summary_text).replace("\n", "<br>")
                _ab = _html.escape(_ai_analysis_text).replace("\n", "<br>")

                # ── 카드 내부 블록 조립 ───────────────────────────────────────
                _inner_html = ""
                if _ab:
                    _inner_html += (
                        '<div style="color:#6A8FA0;font-size:0.62rem;font-weight:700;'
                        'letter-spacing:2px;text-transform:uppercase;margin-bottom:8px">'
                        '🤖 AI BRIEFING</div>'
                        '<p style="margin:0;color:#B8C8D0;font-size:0.9rem;line-height:1.85;">'
                        f'{_ab}</p>'
                    )
                if _ab and _sb:
                    _inner_html += (
                        '<div style="border-top:1px solid rgba(0,240,255,0.15);'
                        'margin:16px 0;"></div>'
                    )
                if _sb:
                    _inner_html += (
                        '<div style="color:#555;font-size:0.62rem;font-weight:700;'
                        'letter-spacing:2px;text-transform:uppercase;margin-bottom:8px">'
                        '📝 POSTING DRAFT</div>'
                        '<p style="margin:0;color:#D0D0D0;font-size:0.9rem;'
                        'line-height:1.85;font-style:italic;">'
                        f'{_sb}</p>'
                    )

                st.markdown(
                    f'<div style="background:rgba(0,240,255,0.04);border:1px solid rgba(0,240,255,0.13);'
                    f'border-left:3px solid rgba(0,240,255,0.45);border-radius:0 12px 12px 0;'
                    f'padding:16px 22px;margin-top:14px;">'
                    f'<div style="color:#555;font-size:0.62rem;font-weight:700;letter-spacing:2px;'
                    f'text-transform:uppercase;margin-bottom:12px">📋 SITUATION SUMMARY</div>'
                    f'{_inner_html}</div>',
                    unsafe_allow_html=True,
                )

            # ── 파싱 실패 시 Raw Response 디버그 뷰어 ──────────────────────────
            if _ir.get("_parse_error"):
                with st.expander("🛠️ API Raw Response (Debug)", expanded=False):
                    st.caption("JSON 파싱 실패 — Gemini가 반환한 원본 텍스트입니다. `logs/api_debug.log` 에도 동일 내용이 기록됩니다.")
                    st.code(
                        _ir.get("_raw_response", "(응답 없음)"),
                        language="text",
                    )

            # "AI 브리핑 → 주제로 사용" 버튼
            # ai_analysis + summary(씨앗 떡밥 풀) 합산 주입 → $topic 다양성 보장
            _ai_briefing = (_ir.get("ai_analysis") or "").strip()
            if _ai_briefing:
                st.markdown('<div class="topic-use-btn" style="margin-top:12px">', unsafe_allow_html=True)
                if st.button("➡️  AI 브리핑 전체를 주제로 사용", key="use_as_topic_btn"):
                    _summary_for_topic = (_ir.get("summary") or "").strip()
                    _full_topic = (
                        _ai_briefing
                        + ("\n씨앗 떡밥: " + _summary_for_topic if _summary_for_topic else "")
                    )
                    ss.swarm_topic_input = _full_topic
                    # ── UX 동기화: INTEL 패널의 갤러리 설정을 FIRE 패널에 그대로 복사 ──
                    ss.target_gallery_id = ss.get("intel_gallery_id", "")
                    ss.target_type_label = ss.get("intel_type_label", "마이너 (mgallery)")
                    st.rerun(scope="app")
                st.markdown('</div>', unsafe_allow_html=True)

        with col_chart:
            # Plotly fig 캐시: intel_result 내용이 바뀔 때만 재생성
            _fig_key = hash(str(_ir.get("top_keywords", [])) + str(_ir.get("keyword_counts", {})))
            if ss.get("_intel_fig_key") != _fig_key or ss.get("_intel_fig") is None:
                ss["_intel_fig"]     = _build_intel_fig(_ir)
                ss["_intel_fig_key"] = _fig_key

            if ss["_intel_fig"] is not None:
                st.plotly_chart(ss["_intel_fig"], use_container_width=True,
                                config={"displayModeBar": False})

        # ── 원본 게시글 디버깅 뷰 (DB 봇 마킹 + Ledger 대조 확인용) ─────────
        # _ai_nos_db / _raw_posts_scan 은 AI OCCUPATION RATE 섹션에서 이미 계산됨.
        _raw_posts = _raw_posts_scan  # 재계산 없이 재사용
        if _raw_posts:
            with st.expander(f"🔍 수집 게시글 원본 ({len(_raw_posts)}개) — 봇 마킹 확인", expanded=False):
                import pandas as pd
                _df_data = [
                    {
                        "글번호": str(p.get("post_no", "")),
                        "제목": str(p.get("title", ""))[:45],
                        "작성자": str(p.get("author", "")),
                        "🤖 봇": "✅ BOT" if (
                            p.get("is_bot")
                            or str(p.get("post_no", "")) in _ai_nos_db
                        ) else "—",
                    }
                    for p in _raw_posts
                ]
                st.dataframe(pd.DataFrame(_df_data), use_container_width=True, hide_index=True)

        # ── DB 원본 데이터 대용량 CSV 내보내기 ──────────────────────────────
        _export_gid = ss.get("intel_gallery_id", "").strip()
        if _export_gid:
            _db_post_cnt = database.get_post_count(_export_gid)
            _db_cmt_cnt  = database.get_comment_count(_export_gid)
            with st.expander(
                f"📥 DB 원본 데이터 내보내기 — 게시글 {_db_post_cnt:,}개 · 댓글 {_db_cmt_cnt:,}개",
                expanded=False,
            ):
                _HARD_LIMIT = database._EXPORT_HARD_LIMIT
                st.caption(
                    f"최대 {_HARD_LIMIT:,}행 · UTF-8 BOM (Excel 한글 호환) · 캐시 5분\n\n"
                    + (f"⚠️ DB 게시글 {_db_post_cnt:,}행 중 {_HARD_LIMIT:,}행만 추출됩니다." if _db_post_cnt > _HARD_LIMIT else "")
                    + (f"\n⚠️ DB 댓글 {_db_cmt_cnt:,}행 중 {_HARD_LIMIT:,}행만 추출됩니다." if _db_cmt_cnt > _HARD_LIMIT else "")
                )

                _dl_c1, _dl_c2 = st.columns(2)

                with _dl_c1:
                    if _db_post_cnt > 0:
                        with st.spinner(f"게시글 CSV 준비 중... ({min(_db_post_cnt, _HARD_LIMIT):,}행)"):
                            _posts_csv, _posts_rows = _cached_posts_csv(_export_gid)
                        st.download_button(
                            f"⬇️ 게시글 CSV ({_posts_rows:,}행)",
                            data=_posts_csv,
                            file_name=f"{_export_gid}_posts.csv",
                            mime="text/csv",
                            key="dl_posts_csv",
                            use_container_width=True,
                        )
                    else:
                        st.info("게시글 없음")

                with _dl_c2:
                    if _db_cmt_cnt > 0:
                        with st.spinner(f"댓글 CSV 준비 중... ({min(_db_cmt_cnt, _HARD_LIMIT):,}행)"):
                            _cmts_csv, _cmts_rows = _cached_comments_csv(_export_gid)
                        st.download_button(
                            f"⬇️ 댓글 CSV ({_cmts_rows:,}행)",
                            data=_cmts_csv,
                            file_name=f"{_export_gid}_comments.csv",
                            mime="text/csv",
                            key="dl_comments_csv",
                            use_container_width=True,
                        )
                    else:
                        st.info("댓글 없음")

    elif ss.get("intel_running"):
        # 수집/분석 진행 중
        if ss.intel_log:
            _lh = "".join(f'<div>{_html.escape(ln)}</div>' for ln in ss.intel_log[-18:])
            st.markdown(
                f'<div class="intel-terminal" style="height:160px;overflow-y:auto">{_lh}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="intel-card"><div class="intel-empty">📡 수집 중...<br><br>'
                '<span style="color:#00F0FF">갤러리 트렌드 데이터를 수집하고 있습니다.</span>'
                '</div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            '<div class="intel-card"><div class="intel-empty">📡 대기 중<br><br>'
            '갤러리 ID를 확인하고<br>'
            '<b style="color:#00F0FF">🔍 분석 시작</b>을 누르세요.<br><br>'
            '<span style="color:#333;font-size:0.72rem">분석 결과는 15분간 캐시됩니다.</span>'
            '</div></div>',
            unsafe_allow_html=True,
        )

    # ── 폴링 제어 ────────────────────────────────────────────────────────
    if _intel_done:
        st.rerun(scope="app")          # 전체 재실행 → 버튼 재활성화
    elif ss.get("intel_running"):
        time.sleep(0.5)
        st.rerun()                     # fragment만 재실행


# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — SWARM 모니터 (Preview + Terminal + Stats + STOP)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _monitor_fragment() -> None:
    """SWARM 실시간 모니터 fragment.

    • swarm_running=True 동안 queue 드레인 → session_state 갱신 → fragment 재실행
    • 전체 페이지 재실행 없이 Preview/Terminal/Stats만 갱신 → Flickering 없음
    • 완료(done) 수신 시 scope='app' 전체 재실행 → FIRE 버튼 재활성화
    """
    ss = st.session_state

    # ── Swarm Queue 드레인 ───────────────────────────────────────────────
    _done_received = False
    if ss.get("swarm_running") and ss.get("swarm_queue") is not None:
        sq: queue.Queue = ss.swarm_queue
        while True:
            try:
                msg = sq.get_nowait()
            except queue.Empty:
                break

            if msg["type"] == "log":
                ss.swarm_log.append(msg["data"])
            elif msg["type"] == "preview":
                ss.swarm_preview_title   = msg["title"]
                ss.swarm_preview_content = msg["content"]
                ss.swarm_wave_current    = msg["wave"]
            elif msg["type"] == "stat":
                ss.posts_success += msg.get("success", 0)
                ss.posts_failed  += msg.get("fail", 0)
            elif msg["type"] == "done":
                ss.swarm_running    = False
                ss.swarm_queue      = None
                ss.swarm_stop_event = None
                _done_received = True

    # ── STOP 버튼 (실행 중일 때만) ───────────────────────────────────────
    if ss.get("swarm_running"):
        st.markdown('<div class="stop-btn">', unsafe_allow_html=True)
        if st.button("🛑  STOP  —  중단", key="stop_btn_frag", use_container_width=True):
            if ss.get("swarm_stop_event"):
                ss.swarm_stop_event.set()
                ss.swarm_log.append("[SWARM] 🛑 중단 요청 전송됨 — 현재 작업 완료 후 종료...")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Preview + Terminal ───────────────────────────────────────────────
    col_preview, col_log = st.columns([3, 2], gap="medium")

    with col_preview:
        st.markdown('<div class="section-hdr">🖥️ AI Post Preview</div>', unsafe_allow_html=True)
        if ss.swarm_preview_title:
            _safe_t   = _html.escape(ss.swarm_preview_title)
            _safe_c   = _html.escape(ss.swarm_preview_content)
            _wave_lbl = (
                f"WAVE {ss.swarm_wave_current}/{ss.swarm_wave_total}"
                if ss.last_fired else "LAST GENERATED"
            )
            st.markdown(
                f'<div class="preview-dark">'
                f'<div class="pd-label">{_html.escape(_wave_lbl)}</div>'
                f'<div class="pd-title">{_safe_t}</div>'
                f'<div class="pd-body">{_safe_c}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="preview-dark">'
                '<div class="pd-empty">대기 중...<br><br>주제를 입력하고<br>🔥 FIRE를 눌러주세요.</div>'
                '</div>',
                unsafe_allow_html=True,
            )

    with col_log:
        st.markdown('<div class="section-hdr">📟 Live Terminal</div>', unsafe_allow_html=True)
        if ss.swarm_log:
            st.markdown(render_terminal(ss.swarm_log, height_px=420), unsafe_allow_html=True)
        else:
            st.markdown(
                '<div class="terminal" style="height:420px">'
                '<div style="color:#30363D;font-style:italic">'
                '// Ghost Protocol v5.0 Launchpad<br>'
                '// Terminal ready — awaiting launch sequence...'
                '</div></div>',
                unsafe_allow_html=True,
            )

    # ── Log Copy — 원클릭 복사 ───────────────────────────────────────────
    # collapsed by default → 폴링 중에도 렌더링 비용 없음.
    # 열면 st.code 우상단 📋 아이콘으로 전체 로그를 한 번에 복사 가능.
    if ss.swarm_log:
        with st.expander("📋 로그 복사", expanded=False):
            st.code("\n".join(ss.swarm_log[-200:]), language="bash")

    # ── Mission Stats + Reset ────────────────────────────────────────────
    _wave_disp = f"{ss.swarm_wave_current}/{ss.swarm_wave_total}" if ss.swarm_wave_total else "—"
    sc1, sc2, sc3, sc4 = st.columns([1, 1, 1, 3])
    with sc1:
        st.markdown(
            f'<div class="ms-pill ms-ok">'
            f'<div class="ms-val">{ss.posts_success}</div>'
            f'<div class="ms-lbl">성공</div></div>',
            unsafe_allow_html=True,
        )
    with sc2:
        st.markdown(
            f'<div class="ms-pill ms-err">'
            f'<div class="ms-val">{ss.posts_failed}</div>'
            f'<div class="ms-lbl">실패</div></div>',
            unsafe_allow_html=True,
        )
    with sc3:
        st.markdown(
            f'<div class="ms-pill ms-wave">'
            f'<div class="ms-val">{_wave_disp}</div>'
            f'<div class="ms-lbl">Wave</div></div>',
            unsafe_allow_html=True,
        )
    with sc4:
        if st.button("🔄 스탯 초기화", key="reset_stats_btn"):
            ss.posts_success          = 0
            ss.posts_failed           = 0
            ss.swarm_log              = []
            ss.swarm_preview_title    = ""
            ss.swarm_preview_content  = ""
            st.rerun(scope="app")

    # ── 폴링 제어 ────────────────────────────────────────────────────────
    if _done_received:
        # 무한 모드: 포스팅 완료 후 다음 배치 자동 시작
        if ss.get("swarm_infinite") and ss.get("_batch_gen_config"):
            _start_next_batch(ss)
        st.rerun(scope="app")          # 전체 재실행 → 버튼 재활성화
    elif ss.get("swarm_running"):
        time.sleep(0.5)
        st.rerun()                     # fragment만 재실행


# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — 배치 대본 생성 진행 모니터
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _batch_gen_fragment() -> None:
    """대본 일괄 생성 진행 상황을 보여주는 fragment.

    • batch_generating=True 동안 batch_gen_queue 드레인 → session_state 갱신
    • batch_done 수신 시 review_ready=True 설정 → scope='app' 재실행
    """
    ss = st.session_state

    _done = False
    if ss.get("batch_generating") and ss.get("batch_gen_queue") is not None:
        bq: queue.Queue = ss.batch_gen_queue
        while True:
            try:
                msg = bq.get_nowait()
            except queue.Empty:
                break

            if msg["type"] == "log":
                ss.swarm_log.append(msg["data"])
            elif msg["type"] == "batch_progress":
                ss.swarm_wave_current = msg["wave"]
                ss.swarm_wave_total   = msg["total"]
            elif msg["type"] == "context_updated":
                # 세계관 갱신 완료 — Intel 패널 + 다음 무한 사이클 토픽 동기화
                _fresh_intel = msg.get("intel")
                if _fresh_intel:
                    ss.intel_result = _fresh_intel
                _cfg = ss.get("_batch_gen_config")
                if _cfg and msg.get("topic"):
                    _cfg["topic"] = msg["topic"]
            elif msg["type"] == "batch_done":
                ss.review_scripts    = msg["scripts"]
                ss.batch_generating  = False
                ss.batch_gen_queue   = None
                if ss.get("swarm_infinite"):
                    # 무한 모드: 검수 게이트 우회 → 포스팅 워커 자동 시작
                    _auto_launch_swarm(ss, msg["scripts"])
                else:
                    ss.review_ready  = bool(msg["scripts"])
                _done = True

    # 중단 버튼
    if ss.get("batch_generating"):
        st.markdown('<div class="stop-btn">', unsafe_allow_html=True)
        if st.button("🛑  생성 중단", key="stop_batch_btn_frag", use_container_width=True):
            if ss.get("batch_gen_stop_event"):
                ss.batch_gen_stop_event.set()
                ss.swarm_log.append("[BATCH] 🛑 생성 중단 요청 전송됨...")
        st.markdown('</div>', unsafe_allow_html=True)

    # 진행률
    _cur   = ss.get("swarm_wave_current", 0)
    _total = ss.get("swarm_wave_total", 0)
    st.markdown(
        f'<div class="section-hdr">🎬 대본 생성 중... {_cur}/{_total} WAVES</div>',
        unsafe_allow_html=True,
    )
    if _total > 0:
        st.progress(_cur / _total)

    # 터미널
    if ss.swarm_log:
        st.markdown(render_terminal(ss.swarm_log, height_px=320), unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="terminal" style="height:320px">'
            '<div style="color:#30363D;font-style:italic">'
            '// Batch generator initializing...'
            '</div></div>',
            unsafe_allow_html=True,
        )

    # 폴링 제어
    if _done:
        st.rerun(scope="app")
    elif ss.get("batch_generating"):
        time.sleep(0.5)
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — 작가 검수 보드
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment
def _review_board_fragment() -> None:
    """생성된 대본을 카드 형태로 펼쳐 보여주는 검수 보드 fragment.

    작가가 내용을 확인 후 [대본 최종 승인] 버튼을 눌러야만 연재가 시작된다.
    [폐기 및 재생성] 버튼은 대본을 삭제하고 IDLE 상태로 복귀.
    """
    ss      = st.session_state
    scripts = ss.get("review_scripts", [])

    if not scripts:
        st.markdown(
            '<div class="pd-empty">생성된 대본이 없습니다.<br>대본 제작 버튼을 다시 눌러주세요.</div>',
            unsafe_allow_html=True,
        )
        return

    valid   = [s for s in scripts if not s.get("_failed")]
    failed  = [s for s in scripts if s.get("_failed")]
    _total  = len(scripts)
    _ok     = len(valid)

    # ── 헤더 + 전체 복사 버튼 ────────────────────────────────────────────
    hdr_col, copy_col = st.columns([4, 1], gap="small")
    with hdr_col:
        st.markdown(
            f'<div class="section-hdr">📋 대본 검수 보드 — {_ok} / {_total} WAVES 생성 완료</div>',
            unsafe_allow_html=True,
        )
    with copy_col:
        if st.button("📋 전체 복사", key="copy_scripts_toggle_btn",
                     help="전체 대본을 Plaintext로 펼쳐 복사합니다", use_container_width=True):
            ss["_show_copy_box"] = not ss.get("_show_copy_box", False)

    if ss.get("_show_copy_box", False):
        _copy_text = _format_scripts_for_copy(scripts)
        st.code(_copy_text, language="text")

    # 대본 카드
    for s in scripts:
        wave        = s["wave"]
        title       = s.get("title", "")
        content     = s.get("content", "")
        failed_flag = s.get("_failed", False)
        persona     = s.get("persona_name", "")
        tone_key    = s.get("tone", "")
        tc_list     = s.get("target_comments", [])

        status_color = "#FF4B4B" if failed_flag else "#00FF88"
        status_text  = "❌ 생성 실패" if failed_flag else "✅"
        card_cls     = "review-card review-card-failed" if failed_flag else "review-card"

        tc_html = ""
        if tc_list:
            tc_parts = [
                f'<span class="intel-chip-kw" style="font-size:0.62rem">'
                f'#{_html.escape(str(tc.get("post_no","?")))}'
                f' → {_html.escape(str(tc.get("comment",""))[:28])}'
                f'</span>'
                for tc in tc_list
            ]
            tc_html = (
                '<div style="margin-top:7px;display:flex;flex-wrap:wrap;gap:4px">'
                + "".join(tc_parts)
                + "</div>"
            )

        if failed_flag:
            body_html = (
                '<div style="color:#555;font-style:italic;font-size:0.78rem">'
                'LLM 생성 실패 — 연재 시 자동 건너뜀</div>'
            )
        else:
            body_html = (
                f'<div class="rc-title">{_html.escape(title)}</div>'
                f'<div class="rc-body">{_html.escape(content)}</div>'
                f'{tc_html}'
            )

        st.markdown(
            f'<div class="{card_cls}" style="border-left:3px solid {status_color}">'
            f'  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
            f'    <span class="rc-wave-badge">WAVE {wave}</span>'
            f'    <span style="color:#555;font-size:0.62rem">{_html.escape(persona)}</span>'
            f'    <span class="intel-chip-kw" style="font-size:0.6rem">{_html.escape(tone_key)}</span>'
            f'    <span style="margin-left:auto;color:{status_color};font-size:0.62rem;font-weight:700">'
            f'      {status_text}</span>'
            f'  </div>'
            f'  {body_html}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

    # 경고 메시지
    if failed:
        st.warning(f"⚠️ {len(failed)}개 Wave는 생성에 실패했습니다. 해당 Wave는 자동으로 건너뜁니다.")

    if not valid:
        st.error("❌ 발행 가능한 대본이 없습니다. 폐기 후 다시 생성하세요.")
        if st.button("🗑️ 폐기 및 재생성", key="review_discard_only_btn", use_container_width=True):
            ss.review_ready   = False
            ss.review_scripts = []
            st.rerun(scope="app")
        return

    # 승인 + 폐기 버튼
    col_confirm, col_discard = st.columns([3, 1], gap="small")

    with col_confirm:
        st.markdown('<div class="confirm-btn">', unsafe_allow_html=True)
        if st.button(
            f"✅  대본 최종 승인 및 연재 시작  —  {_ok} WAVES",
            key="confirm_publish_btn",
            use_container_width=True,
        ):
            # 계정 확인
            try:
                load_accounts()
            except (FileNotFoundError, ValueError) as _ae:
                st.error(f"⚠️ accounts.txt 로드 실패: {str(_ae)}")
                return

            # 연재 실행 워커 시작
            _post_q:  queue.Queue     = queue.Queue()
            _post_ev: threading.Event = threading.Event()

            ss.review_ready          = False
            ss.swarm_running         = True
            ss.swarm_queue           = _post_q
            ss.swarm_stop_event      = _post_ev
            ss.swarm_log             = []
            ss.swarm_preview_title   = ""
            ss.swarm_preview_content = ""
            ss.swarm_wave_total      = _ok
            ss.swarm_wave_current    = 0
            ss.last_fired            = True

            _cfg = ss.get("_batch_gen_config", {})
            threading.Thread(
                target=_post_exec_worker,
                kwargs={
                    "log_q":        _post_q,
                    "stop_ev":      _post_ev,
                    "scripts":      ss.review_scripts,
                    "gallery_id":   _cfg.get("gallery_id", ""),
                    "gallery_type": _cfg.get("gallery_type", "mgallery"),
                    "headless":     _cfg.get("headless", True),
                },
                daemon=True,
            ).start()

            st.rerun(scope="app")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_discard:
        if st.button("🗑️ 폐기", key="review_discard_btn", use_container_width=True,
                     help="대본을 버리고 다시 생성합니다"):
            ss.review_ready   = False
            ss.review_scripts = []
            st.rerun(scope="app")


# ══════════════════════════════════════════════════════════════════════════════
#
#  ██████╗ ███████╗███╗   ██╗██████╗ ███████╗██████╗
# ██╔══██╗██╔════╝████╗  ██║██╔══██╗██╔════╝██╔══██╗
# ██████╔╝█████╗  ██╔██╗ ██║██║  ██║█████╗  ██████╔╝
# ██╔══██╗██╔══╝  ██║╚██╗██║██║  ██║██╔══╝  ██╔══██╗
# ██║  ██║███████╗██║ ╚████║██████╔╝███████╗██║  ██║
# ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═╝  ╚═╝
#
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════
# Sidebar — OTA 업데이터 (left control panel로 이전 — sidebar는 CSS hidden)
# ══════════════════════════════════════════════

# ── 공통 변수 계산 ────────────────────────────────────────────────────────────
has_any_key = bool(_GEMINI_API_KEY)  # .env에서 로드된 키만 사용

# ── API Key 누락 시 전역 경고 배너 ─────────────────────────────────────────
if not _GEMINI_API_KEY:
    st.markdown(
        '<div style="background:rgba(255,75,75,0.08);border:1px solid rgba(255,75,75,0.35);'
        'border-left:4px solid #FF4B4B;border-radius:12px;padding:16px 22px;margin-bottom:18px;'
        'display:flex;align-items:center;gap:14px">'
        '<span style="font-size:1.5rem">🔑</span>'
        '<div>'
        '<div style="font-weight:800;font-size:0.8rem;letter-spacing:2px;'
        'text-transform:uppercase;color:#FF4B4B;margin-bottom:4px">GEMINI API KEY 없음 — 실행 불가</div>'
        '<div style="font-size:0.82rem;color:#AAAAAA;line-height:1.6">'
        '프로젝트 루트에 <code style="background:#1A1A1A;padding:1px 6px;border-radius:4px;'
        'color:#00F0FF">.env</code> 파일을 생성하고 '
        '<code style="background:#1A1A1A;padding:1px 6px;border-radius:4px;color:#00F0FF">'
        'GEMINI_API_KEY=AIza...</code> 를 추가한 뒤 앱을 재시작하세요.<br>'
        '<span style="color:#666;font-size:0.75rem">참고: <code>.env.example</code> 파일을 복사해서 사용하세요.</span>'
        '</div></div></div>',
        unsafe_allow_html=True,
    )

# ══════════════════════════════════════════════
# HEADER BAR — 로고 + Settings Popover
# ══════════════════════════════════════════════
hdr_logo, hdr_spacer, hdr_settings = st.columns([3, 5, 2])

with hdr_logo:
    st.markdown(
        '<div class="logo-text">👻 <span>GHOST</span> PROTOCOL</div>'
        '<div class="logo-sub">v5.0 · Launchpad · Bento 3.0</div>',
        unsafe_allow_html=True,
    )

with hdr_settings:
    st.markdown('<div class="settings-wrap">', unsafe_allow_html=True)
    with st.popover("⚙️  Settings", use_container_width=True):
        # ── API Key 상태 뱃지 (입력란 제거 — .env 전용) ─────────────
        if _GEMINI_API_KEY:
            _masked = f"{'*' * 8}{_GEMINI_API_KEY[-4:]}"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;'
                f'background:rgba(0,255,136,0.07);border:1px solid rgba(0,255,136,0.25);'
                f'border-radius:10px;padding:10px 14px;margin-bottom:14px">'
                f'<span style="font-size:1rem">🔑</span>'
                f'<div>'
                f'<div style="font-size:0.65rem;font-weight:700;letter-spacing:2px;'
                f'text-transform:uppercase;color:#00FF88">API KEY LOADED</div>'
                f'<div style="font-size:0.72rem;color:#888;font-family:monospace;margin-top:2px">'
                f'{_masked}</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="display:flex;align-items:center;gap:8px;'
                'background:rgba(255,75,75,0.08);border:1px solid rgba(255,75,75,0.3);'
                'border-radius:10px;padding:10px 14px;margin-bottom:14px">'
                '<span style="font-size:1rem">🔑</span>'
                '<div>'
                '<div style="font-size:0.65rem;font-weight:700;letter-spacing:2px;'
                'text-transform:uppercase;color:#FF4B4B">API KEY MISSING</div>'
                '<div style="font-size:0.7rem;color:#888;margin-top:2px">'
                '.env 파일에 GEMINI_API_KEY를 추가하세요</div>'
                '</div></div>',
                unsafe_allow_html=True,
            )
            st.caption("📄 `.env.example` 파일을 참고해 `.env`를 생성하세요.")

        st.divider()
        st.markdown(
            '<div style="font-size:0.65rem;font-weight:700;letter-spacing:2px;'
            'text-transform:uppercase;color:#555;margin-bottom:10px">✍️ STYLE</div>',
            unsafe_allow_html=True,
        )
        st.selectbox("Tone", options=list(_TONE_MAP.keys()), key="target_tone_label")
        st.selectbox("Length", options=_LEN_OPTS, key="target_length")
        st.toggle("🕶️ Headless Mode", key="target_headless",
                  help="ON: 숨김 브라우저 / OFF: 디버깅용 화면 표시")

    st.markdown('</div>', unsafe_allow_html=True)

st.markdown(
    '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:0 0 20px 0">',
    unsafe_allow_html=True,
)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN BENTO GRID — Left: Controls (38%) | Right: Output (62%)
# ══════════════════════════════════════════════════════════════════════════════
main_left, main_right = st.columns([38, 62], gap="large")

with main_left:
    # ════════════════════════════════════════
    # STEP 1 — INTEL Control Card
    # ════════════════════════════════════════
    st.markdown('<div class="ctrl-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="ctrl-card-hdr">🔍 STEP 1 — Situation Room</div>',
        unsafe_allow_html=True,
    )

    # ── 갤러리 히스토리 빠른 선택 ────────────────────────────────────────
    _hist_entries = _history_load()
    if _hist_entries:
        st.caption("🕐 최근 분석")
        _hcols = st.columns(min(len(_hist_entries), 4))
        for _hi, _he in enumerate(_hist_entries[:4]):
            with _hcols[_hi]:
                if st.button(
                    _he["gallery_id"],
                    key=f"hist_q_{_he['gallery_id']}",
                    use_container_width=True,
                ):
                    st.session_state.intel_gallery_id = _he["gallery_id"]
                    st.session_state.intel_type_label = _he.get("type_label", "마이너 (mgallery)")
                    st.rerun(scope="app")

    st.text_input(
        "분석할 갤러리 ID",
        key="intel_gallery_id",
        placeholder="예: baseball_new9, soccer_new1, webtoon",
    )
    st.selectbox(
        "갤러리 타입",
        options=list(_TYPE_MAP.keys()),
        key="intel_type_label",
    )
    st.slider("수집 페이지 수", min_value=1, max_value=5, key="intel_pages",
              help="페이지 수↑ = 정확도↑, 수집 시간↑")

    # 캐시 상태 표시
    _igid_now   = st.session_state.get("intel_gallery_id", "")
    _igtype_now = _TYPE_MAP.get(st.session_state.get("intel_type_label", "마이너 (mgallery)"), "mgallery")
    _ick        = f"{_igid_now}::{_igtype_now}"
    _icached    = st.session_state.intel_cache.get(_ick)
    _icache_age: float | None = None
    _icache_valid = False
    if _icached:
        _icache_age   = time.time() - _icached.get("ts", 0)
        _icache_valid = _icache_age < _INTEL_CACHE_TTL
    if _icache_valid and _icache_age is not None:
        st.caption(f"✅ 캐시 유효 — {int(_icache_age//60)}분 {int(_icache_age%60)}초 전 분석")
    elif _icached:
        st.caption("♻️ 캐시 만료 (15분) — 재분석 필요")

    _intel_is_running   = st.session_state.get("intel_running", False)
    _intel_btn_disabled = not has_any_key or not _igid_now.strip() or _intel_is_running

    st.markdown('<div class="intel-run-btn">', unsafe_allow_html=True)
    _intel_fire = st.button(
        "🔍  분석 시작" if not _intel_is_running else "⏳  분석 중...",
        key="intel_fire_btn",
        disabled=_intel_btn_disabled,
        use_container_width=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if not has_any_key:
        st.caption("🔑 .env 파일에 GEMINI_API_KEY를 설정하고 앱을 재시작하세요.")

    st.markdown('</div>', unsafe_allow_html=True)  # /ctrl-card INTEL

    # ════════════════════════════════════════
    # STEP 2 — Payload Control Card
    # ════════════════════════════════════════
    st.markdown('<div class="ctrl-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="ctrl-card-hdr">⚡ STEP 2 — Payload'
        '<span class="bento-step-badge" style="margin-left:8px;vertical-align:middle">'
        'TARGET · TOPIC · WAVE</span></div>',
        unsafe_allow_html=True,
    )

    st.text_input(
        "🎯 폭격할 주제를 입력하세요",
        key="swarm_topic_input",
        placeholder="예: 요즘 분위기 왜 이러냐 / 이슈 터진 거 실화냐 / 다들 어떻게 생각하냐",
    )
    st.text_input(
        "Gallery ID",
        key="target_gallery_id",
        placeholder="예: baseball_new9",
        help="DC Inside 갤러리 ID",
    )

    _pay_c1, _pay_c2 = st.columns([3, 2])
    with _pay_c1:
        st.selectbox(
            "갤러리 타입",
            options=list(_TYPE_MAP.keys()),
            key="target_type_label",
            help="정규→board / 마이너→mgallery",
        )
    with _pay_c2:
        st.number_input(
            "💣 WAVE",
            min_value=1, max_value=50, step=1,
            key="swarm_wave_count",
            help="연속 폭격 횟수 (무한 모드 ON 시 자동으로 10으로 고정됨)",
            # 무한 모드 활성화 시 wave 수 설정이 무의미 → 입력창 비활성화
            disabled=st.session_state.get("swarm_infinite", False),
        )

    st.checkbox(
        "♾️ 무한 모드 (Infinite Run)",
        key="swarm_infinite",
        help="활성화 시 WAVE 완료 후 10~30분 랜덤 쿨타임을 두고 무한 반복. 🛑 STOP으로 중단.",
    )

    # 재계산 (위젯 렌더 후 값 갱신)
    _gallery_id   = st.session_state.get("target_gallery_id", "")
    _gallery_type = _TYPE_MAP.get(st.session_state.get("target_type_label", "마이너 (mgallery)"), "mgallery")
    _neural_tone  = _TONE_MAP.get(st.session_state.get("target_tone_label", "🧊 냉소적 (Cynical)"), "cynical")
    _length       = st.session_state.get("target_length", "보통 (3~4문장)")
    _headless     = st.session_state.get("target_headless", True)
    st.markdown(
        f'<div class="config-summary" style="margin-top:8px">'
        f'<div class="cs-row"><span class="cs-label">Tone</span><span class="cs-val">{_neural_tone}</span></div>'
        f'<div class="cs-row"><span class="cs-label">Length</span><span class="cs-val">{_length.split(" ")[0]}</span></div>'
        f'<div class="cs-row"><span class="cs-label">Headless</span><span class="cs-val">{"ON" if _headless else "OFF"}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)  # /ctrl-card PAYLOAD

    # ════════════════════════════════════════
    # STEP 3 — Generate Script Button
    # ════════════════════════════════════════
    _topic_val      = st.session_state.get("swarm_topic_input", "").strip()
    _is_running     = st.session_state.get("swarm_running", False)
    _is_generating  = st.session_state.get("batch_generating", False)
    _is_reviewing   = st.session_state.get("review_ready", False)
    _any_busy       = _is_running or _is_generating or _is_reviewing
    _fire_disabled  = not has_any_key or not _topic_val or _any_busy

    if _is_generating:
        _btn_label = "⏳  대본 생성 중..."
    elif _is_reviewing:
        _btn_label = "📋  검수 대기 중..."
    elif _is_running:
        _btn_label = "📬  연재 발행 중..."
    else:
        _btn_label = "🎬  대본 제작  —  생성 시작"

    st.markdown('<div class="generate-btn">', unsafe_allow_html=True)
    fire_clicked = st.button(
        _btn_label,
        use_container_width=True,
        type="primary",
        disabled=_fire_disabled,
    )
    st.markdown('</div>', unsafe_allow_html=True)

    if not _any_busy and _fire_disabled:
        if not has_any_key:
            st.caption("🔑 .env 파일에 GEMINI_API_KEY를 설정하고 앱을 재시작하세요.")
        elif not _topic_val:
            st.caption("🎯 Step 2에서 폭격할 주제를 입력하면 활성화됩니다.")

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

    # ── OTA Update (sidebar 대체 — sidebar는 CSS hidden) ─────────────────
    if st.button("🔄 업데이트 (Git Pull)", use_container_width=True,
                 help="git pull + 프롬프트 캐시 초기화. 코드·프롬프트 변경사항을 즉시 반영합니다."):
        # 1) 프롬프트 캐시 초기화 — .txt/.json 변경사항 즉시 반영
        pm._read_file.cache_clear()
        pm.load_json.cache_clear()
        # 2) git pull — 코드 변경사항 수신
        _r = subprocess.run(
            ["git", "pull"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent),
        )
        _out = (_r.stdout or _r.stderr or "").strip()
        st.toast(
            f"📂 프롬프트 캐시 초기화 완료\n{_out or 'Git pull 완료'}",
            icon="✅" if _r.returncode == 0 else "❌",
        )
        st.rerun()

def _do_killswitch():
    """무한 모드 Kill Switch 콜백 — on_click에서 실행되므로 위젯 렌더 전에 호출됨."""
    _ss = st.session_state
    _ss.swarm_infinite = False
    if _ss.get("batch_gen_stop_event"):
        _ss.batch_gen_stop_event.set()
    if _ss.get("swarm_stop_event"):
        _ss.swarm_stop_event.set()


with main_right:
    # ── 무한 모드 전역 Kill Switch 배너 ──────────────────────────────────
    # fragment 바깥에 배치 → batch_gen / swarm / 전환 공백 구간 모두 커버.
    # swarm_infinite=True 인 한 항상 렌더된다.
    _ss_ks = st.session_state
    if _ss_ks.get("swarm_infinite"):
        _ks_col_info, _ks_col_btn = st.columns([3, 1], gap="small")
        with _ks_col_info:
            st.markdown(
                '<div style="font-size:0.72rem;font-weight:700;color:#FF6B35;'
                'letter-spacing:1px;padding:6px 0">♾️ INFINITE MODE 실행 중</div>',
                unsafe_allow_html=True,
            )
        with _ks_col_btn:
            st.button("⏹ 루프 중단", key="infinite_killswitch_btn",
                      on_click=_do_killswitch,
                      use_container_width=True, type="primary",
                      help="현재 Wave 완료 후 무한 루프를 즉시 중단합니다")

    # ── STEP 1 결과 (Situation Room — fragment) ──────────────────────────
    _intel_results_fragment()

    st.markdown(
        '<hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:20px 0 16px 0">',
        unsafe_allow_html=True,
    )

    # ── STEP 3 영역: 상태에 따라 fragment 전환 ───────────────────────────
    _ss = st.session_state
    if _ss.get("batch_generating"):
        st.markdown(
            '<div style="font-size:0.68rem;font-weight:800;letter-spacing:3px;'
            'text-transform:uppercase;color:#00FF88;margin-bottom:10px;'
            'text-shadow:0 0 10px rgba(0,255,136,0.3)">🎬 STEP 3 — Script Generation</div>',
            unsafe_allow_html=True,
        )
        _batch_gen_fragment()

    elif _ss.get("review_ready") and not _ss.get("swarm_running"):
        st.markdown(
            '<div style="font-size:0.68rem;font-weight:800;letter-spacing:3px;'
            'text-transform:uppercase;color:#AAFF44;margin-bottom:10px;'
            'text-shadow:0 0 10px rgba(170,255,68,0.3)">📋 STEP 3 — Review Board</div>',
            unsafe_allow_html=True,
        )
        _review_board_fragment()

    else:
        st.markdown(
            '<div style="font-size:0.68rem;font-weight:800;letter-spacing:3px;'
            'text-transform:uppercase;color:#FF4B4B;margin-bottom:10px;'
            'text-shadow:0 0 10px rgba(255,75,75,0.35)">📬 STEP 3 — Launch &amp; Monitor</div>',
            unsafe_allow_html=True,
        )
        _monitor_fragment()


# ══════════════════════════════════════════════════════════════════════════════
# 대본 제작 버튼 — 배치 생성 워커 시작 (포스팅 없음)
# ══════════════════════════════════════════════════════════════════════════════
if fire_clicked:
    _topic    = st.session_state.get("swarm_topic_input", "").strip()
    _w_count  = st.session_state.get("swarm_wave_count", 3)
    _infinite = bool(st.session_state.get("swarm_infinite", False))

    if not has_any_key:
        st.error("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. 프로젝트 루트의 .env 파일을 확인하고 앱을 재시작하세요.")
    elif not _topic:
        st.error("⚠️ 주제를 입력하세요.")
    else:
        # Phase 10: 무한 모드 변수 누수 방지 — UI 캐시값(swarm_wave_count)과 무관하게 10 강제
        # min(_w_count, 10) 패턴은 유저가 3으로 설정한 채 infinite ON 하면 3개만 도는 버그 유발.
        _actual_count = 10 if _infinite else _w_count

        # 무한 모드 재배치를 위한 설정 저장
        st.session_state["_batch_gen_config"] = {
            "api_key":      _GEMINI_API_KEY,
            "topic":        _topic,
            "wave_count":   _actual_count,
            "gallery_id":   _gallery_id,
            "gallery_type": _gallery_type,
            "tone":         _neural_tone,
            "length":       _length,
            "headless":     _headless,
            "infinite":     _infinite,
        }

        st.session_state.swarm_log            = []
        st.session_state.swarm_preview_title  = ""
        st.session_state.swarm_preview_content = ""
        st.session_state.swarm_wave_total     = _actual_count
        st.session_state.swarm_wave_current   = 0
        st.session_state.review_scripts       = []
        st.session_state.review_ready         = False
        st.session_state.batch_generating     = True

        _bgq:  queue.Queue     = queue.Queue()
        _bgev: threading.Event = threading.Event()
        st.session_state.batch_gen_queue      = _bgq
        st.session_state.batch_gen_stop_event = _bgev

        threading.Thread(
            target=_batch_gen_worker,
            kwargs={
                "log_q":        _bgq,
                "stop_ev":      _bgev,
                "api_key":      _GEMINI_API_KEY,
                "topic":        _topic,
                "wave_count":   _actual_count,
                "gallery_id":   _gallery_id,
                "gallery_type": _gallery_type,
                "tone":         _neural_tone,
                "length":       _length,
                "infinite":     _infinite,
            },
            daemon=True,
        ).start()

        st.rerun()  # _batch_gen_fragment 폴링 진입


# ══════════════════════════════════════════════
# INTEL FIRE — 분석 워커 시작
# ══════════════════════════════════════════════
if _intel_fire:
    _igid = st.session_state.get("intel_gallery_id", "").strip()

    if not has_any_key:
        st.error("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. 프로젝트 루트의 .env 파일을 확인하고 앱을 재시작하세요.")
    elif not _igid:
        st.error("⚠️ 갤러리 ID를 입력하세요.")
    elif _icache_valid and _icached:
        # 캐시 히트 → 워커 없이 즉시 표시
        st.session_state.intel_result = _icached["result"]
        st.rerun()
    else:
        st.session_state.intel_log     = []
        st.session_state.intel_result  = None
        st.session_state.intel_running = True

        _intel_q: queue.Queue = queue.Queue()
        st.session_state.intel_queue = _intel_q

        threading.Thread(
            target=_intel_worker,
            kwargs={
                "log_q":        _intel_q,
                "api_key":      _GEMINI_API_KEY,
                "gallery_id":   _igid,
                "gallery_type": _igtype_now,
                "pages":        st.session_state.get("intel_pages", 3),
            },
            daemon=True,
        ).start()

        st.rerun()  # fragment가 이후 polling 담당
