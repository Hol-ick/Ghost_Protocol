"""Ghost Protocol v5.0 — LAUNCHPAD
One-Page Stealth Dashboard · Bento 2.0 Redesign

Pipeline: INTEL (Trend Analysis) → PAYLOAD (Topic + Config) → LAUNCH (FIRE + Monitor)
@st.fragment 기반 부분 재렌더링으로 Flickering 완전 제거.

실행: streamlit run app.py
"""

import asyncio
import html as _html
import json
import os
import queue
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

from ghost_protocol import database
from ghost_protocol.brain import GhostBrain, RateLimitError
from ghost_protocol.poster import GhostPoster, load_accounts

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
    "🧊 냉소적 (Cynical)":    "cynical",
    "😐 중립 (Neutral)":      "neutral",
    "📊 분석적 (Analytical)": "analytical",
    "🗣️ 독백 (Monologue)":   "monologue",
    "🔥 공격적 (Aggressive)": "aggressive",
    "💀 어그로성 (Aggro)":    "aggro",
}
_LEN_OPTS = ["아주 짧게 (1문장)", "짧게 (1~2문장)", "보통 (3~4문장)"]
_INTEL_CACHE_TTL = 900  # 15분

# ── SWARM 다중 인격 풀 ─────────────────────────────────────────────────────
# 매 WAVE마다 랜덤으로 한 가지 페르소나를 선택하여 글투 다양성 확보.
# "key"는 brain.py generate_post()의 tone_desc 맵과 1:1 대응.
# UI의 고정 톤 설정을 SWARM 내에서 오버라이드함 — 현지인 군중 시뮬레이션.
_PERSONA_POOL = [
    {"name": "다혈질 분노조절 실패형",  "key": "aggressive"},
    {"name": "무기력한 갤러리 지박령",  "key": "monologue"},
    {"name": "비꼬는 시니컬 관전자",    "key": "cynical"},
    {"name": "실없이 쪼개는 어그로형",  "key": "aggro"},
    {"name": "건조한 무감각 관찰자",    "key": "neutral"},
    {"name": "팩트폭격 분석충",         "key": "analytical"},
    {"name": "분위기 환기형 마이웨이",  "key": "ventilator"},
]

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
) -> None:
    """백그라운드 스레드: Swarm Loop 전체를 실행.
    UI와는 오직 queue.Queue를 통해서만 통신한다.
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

    # ── 댓글 타겟 후보 수집 (SWARM 시작 시 1회 스냅샷) ─────────────────────
    # 봇 게시글(is_bot=True) 필터링: 자문자답 루프 방지
    # Phase 3.6 현재: 데이터 파이프라인 검증 전용 — 브라우저 자동화 없음.
    _recent_posts: list[dict] = []
    try:
        from ghost_protocol.scraper import TrendScraper as _TS
        _ts = _TS()
        _raw_list = _ts.fetch_post_list(gallery_id, gallery_type, page=1)
        _recent_posts = [
            {"post_no": p["post_no"], "title": p["title"]}
            for p in _raw_list[:5]
            # is_bot 필터 해제 (Phase 3.7): 자체 생성 스레드 연속성 통합 테스트 허용.
            # 이전 WAVE에서 작성한 글에도 댓글 가능 → Echo Chamber 스레드 구성 검증.
        ]
        q_log(f"[SWARM] 📋 댓글 타겟 후보 수집 완료: {len(_recent_posts)}개")
    except Exception as _te:
        q_log(f"[SWARM] ⚠️ 댓글 타겟 수집 실패 (SWARM 계속): {str(_te)[:80]}")
        _recent_posts = []

    for wave in range(1, wave_count + 1):
        if stop_ev.is_set():
            q_log("[SWARM] 🛑 중단 요청 — 루프 종료")
            break

        q_log(f"═══════ WAVE {wave}/{wave_count} ═══════")
        q_log(f"[W{wave}] 🧠 AI 작문 시작 → 주제: '{topic[:30]}'")
        q_preview("", "", wave, "GENERATING")

        gen_title: str | None = None
        gen_content: str = ""
        _tc_list: list[dict] = []   # Wave 스코프 초기화 — 항상 정의됨 보장

        # ── 다중 인격 랜덤 배정 ───────────────────────────────────────────────
        # UI 톤 설정을 오버라이드하여 매 Wave마다 다른 현지인 말투로 작성.
        _persona   = random.choice(_PERSONA_POOL)
        _wave_tone = _persona["key"]
        q_log(f"[W{wave}] 🎭 부여된 페르소나: {_persona['name']} ({_wave_tone})")

        for attempt in range(3):
            if stop_ev.is_set():
                break
            try:
                result = brain.generate_post(
                    topic=topic,
                    gallery_id=gallery_id,
                    tone=_wave_tone,
                    context_hours=None,
                    length=length,
                    recent_posts=_recent_posts or None,
                )
                # ── Fail-Safe: 파싱 실패 시 WAVE 즉시 Abort ────────────────
                # "_parse_error" 플래그 또는 빈 title/content → raw 텍스트 포스팅 원천 차단
                # target_comments 실패는 Wave Abort 사유가 아님 (빈 배열로 safe fallback)
                if result.get("_parse_error") or not result.get("title") or not result.get("content"):
                    q_log(f"[W{wave}] ❌ 생성 파싱 실패 (Fail-Safe Abort) — WAVE {wave} 건너뜀")
                    gen_title = None
                    break
                gen_title   = result["title"]
                gen_content = result["content"]
                q_log(f"[W{wave}] ✅ 생성 완료: '{gen_title[:30]}'")

                # ── 댓글 타겟 로그 (Phase 3.6 — 데이터 검증) ────────────────
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

        # ── 계정 큐에서 다음 계정 순서대로 선택 ────────────────────────────
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

        # ── 댓글 자동화 (target_comments 순회 실행) ──────────────────────────
        # 포스팅 성공 여부와 무관하게 실행 (Gemini 스펙 "성공 또는 생략" 해석).
        # 계정은 동일 Wave 계정(_wave_account) 재사용 → 포스팅과 같은 계정으로 댓글.
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

                # 댓글 간 인간다운 딜레이 (마지막 댓글 후는 생략 — Wave 간 딜레이로 흡수)
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
        # 데이터: _ir["stats"]["ai_post_count"] / ["total_post_count"]
        # → brain.analyze_trend()가 scraper.collect_trending() 결과에서 직접 주입.
        # 백엔드 변경 불필요 — 이미 result dict에 포함되어 있음.
        _ai_cnt    = int(_stats_d.get("ai_post_count",    0))
        _total_cnt = int(_stats_d.get("total_post_count", 0))
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

            # "FIRE 주제로 사용" 버튼
            _hot = _ir.get("hot_topics", [])
            if _hot:
                st.markdown('<div class="topic-use-btn" style="margin-top:12px">', unsafe_allow_html=True)
                if st.button(f"➡️  '{_hot[0]}'  —  FIRE 주제로 사용", key="use_as_topic_btn"):
                    ss.swarm_topic_input = _hot[0]
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

        # ── 원본 게시글 디버깅 뷰 (ledger 대조 확인용) ─────────────────────
        _raw_posts = _ir.get("raw_posts", [])
        if _raw_posts:
            with st.expander(f"🔍 수집 게시글 원본 ({len(_raw_posts)}개) — Ledger 대조 디버깅", expanded=False):
                import pandas as pd
                _df_data = [
                    {
                        "글번호": str(p.get("post_no", "")),
                        "제목": str(p.get("title", ""))[:45],
                        "작성자": str(p.get("author", "")),
                        "🤖 봇": "✅ BOT" if p.get("is_bot") else "—",
                    }
                    for p in _raw_posts[:100]
                ]
                st.dataframe(pd.DataFrame(_df_data), use_container_width=True, hide_index=True)

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
        st.rerun(scope="app")          # 전체 재실행 → FIRE 버튼 재활성화
    elif ss.get("swarm_running"):
        time.sleep(0.5)
        st.rerun()                     # fragment만 재실행


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
# Sidebar — OTA 업데이터
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("### ⚙️ 시스템")
    if st.button("🔄 업데이트 (Git Pull)", use_container_width=True,
                 help="git pull 로 최신 코드를 받아 앱을 즉시 반영합니다."):
        _r = subprocess.run(
            ["git", "pull"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent),
        )
        _out = (_r.stdout or _r.stderr or "").strip()
        st.toast(
            _out or "Git pull 완료",
            icon="✅" if _r.returncode == 0 else "❌",
        )
        st.rerun()

# ── 공통 변수 계산 ────────────────────────────────────────────────────────────
has_any_key = bool(_GEMINI_API_KEY)  # .env에서 로드된 키만 사용

_gallery_id   = st.session_state.get("target_gallery_id", "stockus")
_gallery_type = _TYPE_MAP.get(st.session_state.get("target_type_label",  "마이너 (mgallery)"), "mgallery")
_neural_tone  = _TONE_MAP.get(st.session_state.get("target_tone_label",  "🧊 냉소적 (Cynical)"),  "cynical")
_length       = st.session_state.get("target_length",   "보통 (3~4문장)")
_headless     = st.session_state.get("target_headless", True)
_is_running   = st.session_state.get("swarm_running",   False)


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
        '<div class="logo-sub">v5.0 · Launchpad · Bento 2.0</div>',
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
# STEP 1 — INTEL BENTO (Expander)
# ══════════════════════════════════════════════════════════════════════════════
with st.expander("🔍  STEP 1  —  SITUATION ROOM  ·  TREND ANALYSIS"):

    _intel_ctrl, _intel_result_area = st.columns([1, 2], gap="large")

    # ── 컨트롤 패널 ─────────────────────────────────────────────────────
    with _intel_ctrl:
        # ── 갤러리 히스토리 빠른 선택 ────────────────────────────────────
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

        _intel_is_running  = st.session_state.get("intel_running", False)
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

    # ── 결과 패널 (fragment) ─────────────────────────────────────────────
    with _intel_result_area:
        _intel_results_fragment()


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — PAYLOAD BENTO (타겟 + 주제 + Wave)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    '<div class="bento-step">'
    '<div class="bento-step-header">'
    '<span class="bento-step-title">⚡ Step 2  —  Payload</span>'
    '<span class="bento-step-badge">TARGET · TOPIC · WAVE</span>'
    '</div>',
    unsafe_allow_html=True,
)

pay_left, pay_right = st.columns([3, 1], gap="large")

with pay_left:
    st.text_input(
        "🎯 폭격할 주제를 입력하세요",
        key="swarm_topic_input",
        placeholder="예: 요즘 분위기 왜 이러냐 / 이슈 터진 거 실화냐 / 다들 어떻게 생각하냐",
    )
    st.slider(
        "💣 WAVE 횟수",
        min_value=1, max_value=10, key="swarm_wave_count",
        help="연속 폭격 횟수. 각 WAVE 사이에 60~180초 랜덤 대기.",
    )

with pay_right:
    st.text_input(
        "Gallery ID",
        key="target_gallery_id",
        placeholder="예: baseball_new9",
        help="DC Inside 갤러리 ID",
    )
    st.selectbox(
        "갤러리 타입",
        options=list(_TYPE_MAP.keys()),
        key="target_type_label",
        help="정규→board / 마이너→mgallery",
    )
    # 재계산 (위젯 렌더 후 갱신)
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

st.markdown('</div>', unsafe_allow_html=True)  # /bento-step


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — LAUNCH & MONITOR BENTO
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    '<div class="bento-step">'
    '<div class="bento-step-header">'
    '<span class="bento-step-title">🔥 Step 3  —  Launch & Monitor</span>'
    '<span class="bento-step-badge">SWARM MODE</span>'
    '</div>',
    unsafe_allow_html=True,
)

_topic_val    = st.session_state.get("swarm_topic_input", "").strip()
_is_running   = st.session_state.get("swarm_running", False)
_fire_disabled = not has_any_key or not _topic_val or _is_running

st.markdown('<div class="fire-btn">', unsafe_allow_html=True)
fire_clicked = st.button(
    "🔥  FIRE  —  폭격 개시" if not _is_running else "⏳  SWARM RUNNING...",
    use_container_width=True,
    type="primary",
    disabled=_fire_disabled,
)
st.markdown('</div>', unsafe_allow_html=True)

if not _is_running and _fire_disabled:
    if not has_any_key:
        st.caption("🔑 .env 파일에 GEMINI_API_KEY를 설정하고 앱을 재시작하세요.")
    elif not _topic_val:
        st.caption("🎯 Step 2에서 폭격할 주제를 입력하면 활성화됩니다.")

st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# ── Monitor Fragment (Preview + Terminal + Stats + STOP) ────────────────────
_monitor_fragment()

st.markdown('</div>', unsafe_allow_html=True)  # /bento-step


# ══════════════════════════════════════════════
# FIRE — 백그라운드 워커 시작
# ══════════════════════════════════════════════
if fire_clicked:
    _topic   = st.session_state.get("swarm_topic_input", "").strip()
    _w_count = st.session_state.get("swarm_wave_count", 3)

    if not has_any_key:
        st.error("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. 프로젝트 루트의 .env 파일을 확인하고 앱을 재시작하세요.")
    elif not _topic:
        st.error("⚠️ 주제를 입력하세요.")
    else:
        try:
            _accounts = load_accounts()
        except (FileNotFoundError, ValueError) as _e:
            st.error(f"⚠️ accounts.txt 로드 실패: {str(_e)}")
            _accounts = None

        if _accounts:
            st.session_state.swarm_log              = []
            st.session_state.swarm_preview_title    = ""
            st.session_state.swarm_preview_content  = ""
            st.session_state.swarm_wave_total        = _w_count
            st.session_state.swarm_wave_current      = 0
            st.session_state.last_fired              = True
            st.session_state.swarm_running           = True

            _log_q: queue.Queue     = queue.Queue()
            _stop_ev: threading.Event = threading.Event()
            st.session_state.swarm_queue      = _log_q
            st.session_state.swarm_stop_event = _stop_ev

            threading.Thread(
                target=_swarm_worker,
                kwargs={
                    "log_q":        _log_q,
                    "stop_ev":      _stop_ev,
                    "api_key":      _GEMINI_API_KEY,
                    "topic":        _topic,
                    "wave_count":   _w_count,
                    "gallery_id":   _gallery_id,
                    "gallery_type": _gallery_type,
                    "tone":         _neural_tone,
                    "length":       _length,
                    "headless":     _headless,
                },
                daemon=True,
            ).start()

            st.rerun()  # 폴링 모드 진입 (fragment가 이후 polling 담당)


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
