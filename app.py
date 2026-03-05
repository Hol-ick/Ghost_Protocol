"""Ghost Protocol v5.0 — LAUNCHPAD

Pipeline (Swarm Mode): TOPIC → GENERATE → POST
스캔 단계 없음 — 주제 직접 입력 후 즉시 폭격.

실행: streamlit run app.py
"""

import asyncio
import html as _html
import os
import queue
import random
import sys
import threading
import time

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

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
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════
# CSS — Stealth Dark Bento Theme
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
    /* Streamlit 내부 베이지/흰 배경 초기화 */
    [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"],
    [data-testid="column"] {
        background-color: transparent !important;
    }
    .stMainBlockContainer { padding-top: 1.5rem !important; }

    /* ═══ 2. 사이드바 ═══ */
    section[data-testid="stSidebar"] > div {
        background-color: #1A1A1A !important;
        border-right: 1px solid rgba(255,255,255,0.08) !important;
    }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p { color: #FAFAFA !important; }

    /* ═══ 3. 사이드바 로고 ═══ */
    .sb-logo {
        text-align: center !important;
        font-size: 1.1rem !important;
        font-weight: 900 !important;
        letter-spacing: 3px !important;
        color: #FAFAFA !important;
        padding: 8px 0 4px 0 !important;
    }
    .sb-logo span { color: #00F0FF !important; }
    .sb-sub {
        text-align: center !important;
        font-size: 0.68rem !important;
        color: #888888 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        margin-bottom: 4px !important;
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

    /* ═══ 6. Command Center 카드 ═══ */
    .command-center {
        background: #1A1A1A !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 18px !important;
        padding: 28px 32px !important;
        margin-bottom: 18px !important;
    }
    .cc-header {
        display: flex !important;
        align-items: center !important;
        gap: 10px !important;
        margin-bottom: 20px !important;
    }
    .cc-title {
        color: #00F0FF !important;
        font-size: 0.75rem !important;
        font-weight: 800 !important;
        letter-spacing: 4px !important;
        text-transform: uppercase !important;
        text-shadow: 0 0 12px rgba(0,240,255,0.5) !important;
    }
    .cc-badge {
        background: rgba(0,240,255,0.1) !important;
        border: 1px solid rgba(0,240,255,0.3) !important;
        border-radius: 20px !important;
        padding: 2px 10px !important;
        color: #00F0FF !important;
        font-size: 0.65rem !important;
        font-weight: 600 !important;
        letter-spacing: 1px !important;
    }
    .cc-target-info {
        background: rgba(255,255,255,0.03) !important;
        border: 1px solid rgba(255,255,255,0.07) !important;
        border-radius: 10px !important;
        padding: 12px 16px !important;
        margin-top: 8px !important;
    }
    .cti-row {
        display: flex !important;
        justify-content: space-between !important;
        align-items: center !important;
        margin-bottom: 6px !important;
    }
    .cti-row:last-child { margin-bottom: 0 !important; }
    .cti-label { color: #888888 !important; font-size: 0.68rem !important; letter-spacing: 1px !important; text-transform: uppercase !important; }
    .cti-val { color: #E6EDF3 !important; font-size: 0.78rem !important; font-weight: 600 !important; font-family: monospace !important; }
    .command-center .stTextInput input,
    .command-center input[type="text"] {
        background-color: rgba(255,255,255,0.06) !important;
        color: #FAFAFA !important;
        -webkit-text-fill-color: #FAFAFA !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 8px !important;
    }
    .command-center label { color: #AAAAAA !important; }

    /* ═══ 7. FIRE 버튼 ═══ */
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

    /* ═══ 9. Preview 카드 (bento dark) ═══ */
    .preview-dark {
        background: #1E1E1E !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 12px !important;
        padding: 22px !important;
        min-height: 360px !important;
    }
    .pd-label {
        color: #BC8CFF !important;
        font-size: 0.65rem !important;
        font-weight: 700 !important;
        letter-spacing: 3px !important;
        text-transform: uppercase !important;
        margin-bottom: 10px !important;
    }
    .pd-title {
        color: #FAFAFA !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        margin-bottom: 14px !important;
        padding-bottom: 12px !important;
        border-bottom: 1px solid rgba(255,255,255,0.1) !important;
        line-height: 1.4 !important;
    }
    .pd-body {
        color: #CCCCCC !important;
        font-size: 0.9rem !important;
        line-height: 1.75 !important;
        white-space: pre-wrap !important;
    }
    .pd-empty {
        color: #555555 !important;
        font-style: italic !important;
        text-align: center !important;
        padding: 60px 0 !important;
        font-size: 0.85rem !important;
    }
    .pd-status {
        color: #00FF00 !important;
        font-size: 0.65rem !important;
        font-weight: 600 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        margin-top: 14px !important;
        padding-top: 10px !important;
        border-top: 1px solid rgba(255,255,255,0.08) !important;
    }

    /* ═══ 10. 섹션 헤더 ═══ */
    .section-hdr {
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        letter-spacing: 2.5px !important;
        text-transform: uppercase !important;
        color: #888888 !important;
        margin-bottom: 12px !important;
    }

    /* ═══ 11. 스탯 카드 (사이드바) ═══ */
    .stat-row {
        display: flex !important;
        gap: 8px !important;
        margin-top: 4px !important;
    }
    .stat-card {
        flex: 1 !important;
        background: #1E1E1E !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 10px !important;
        padding: 10px 8px !important;
        text-align: center !important;
    }
    .stat-val { font-size: 1.4rem !important; font-weight: 800 !important; color: #FAFAFA !important; }
    .stat-label { font-size: 0.62rem !important; color: #888888 !important; text-transform: uppercase !important; letter-spacing: 1px !important; }
    .stat-ok .stat-val { color: #00FF00 !important; }
    .stat-err .stat-val { color: #FF4B4B !important; }

    /* ═══ 12. Progress Bar ═══ */
    .stProgress > div > div {
        background: linear-gradient(90deg, #FF4B4B, #BC8CFF) !important;
    }

    /* ═══ 13. INTEL 브리핑 카드 ═══ */
    .intel-card {
        background: #141820 !important;
        border: 1px solid rgba(0,240,255,0.18) !important;
        border-radius: 18px !important;
        padding: 24px 28px !important;
        margin-top: 12px !important;
    }
    .intel-header {
        display: flex !important;
        align-items: center !important;
        gap: 10px !important;
        margin-bottom: 18px !important;
        border-bottom: 1px solid rgba(0,240,255,0.12) !important;
        padding-bottom: 12px !important;
    }
    .intel-title {
        color: #00F0FF !important;
        font-size: 0.72rem !important;
        font-weight: 800 !important;
        letter-spacing: 4px !important;
        text-transform: uppercase !important;
        text-shadow: 0 0 10px rgba(0,240,255,0.4) !important;
    }
    .intel-gallery-badge {
        background: rgba(0,240,255,0.08) !important;
        border: 1px solid rgba(0,240,255,0.25) !important;
        border-radius: 20px !important;
        padding: 2px 10px !important;
        color: #00F0FF !important;
        font-size: 0.65rem !important;
        font-family: monospace !important;
    }
    .intel-cache-ts {
        margin-left: auto !important;
        color: #444 !important;
        font-size: 0.62rem !important;
        font-family: monospace !important;
    }
    /* 감성 배지 */
    .intel-sentiment {
        display: inline-block !important;
        padding: 4px 14px !important;
        border-radius: 20px !important;
        font-size: 0.78rem !important;
        font-weight: 700 !important;
        letter-spacing: 1px !important;
        margin-bottom: 16px !important;
    }
    .intel-sentiment-panic    { background: rgba(255,75,75,0.15) !important; color: #FF4B4B !important; border: 1px solid rgba(255,75,75,0.35) !important; }
    .intel-sentiment-hostile  { background: rgba(255,100,0,0.15) !important; color: #FF6400 !important; border: 1px solid rgba(255,100,0,0.35) !important; }
    .intel-sentiment-mock     { background: rgba(188,140,255,0.15) !important; color: #BC8CFF !important; border: 1px solid rgba(188,140,255,0.35) !important; }
    .intel-sentiment-friendly { background: rgba(0,255,0,0.1) !important; color: #00FF88 !important; border: 1px solid rgba(0,255,0,0.3) !important; }
    .intel-sentiment-neutral  { background: rgba(255,255,255,0.07) !important; color: #AAAAAA !important; border: 1px solid rgba(255,255,255,0.15) !important; }
    /* 섹션 라벨 */
    .intel-section-label {
        color: #555 !important;
        font-size: 0.62rem !important;
        font-weight: 700 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        margin-bottom: 8px !important;
    }
    /* 토픽·키워드 칩 */
    .intel-chips { display: flex !important; flex-wrap: wrap !important; gap: 6px !important; margin-bottom: 14px !important; }
    .intel-chip-hot {
        background: rgba(255,75,75,0.12) !important;
        border: 1px solid rgba(255,75,75,0.3) !important;
        border-radius: 20px !important;
        padding: 3px 10px !important;
        color: #FF8080 !important;
        font-size: 0.73rem !important;
        font-weight: 600 !important;
    }
    .intel-chip-kw {
        background: rgba(255,255,255,0.05) !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 20px !important;
        padding: 2px 8px !important;
        color: #888 !important;
        font-size: 0.65rem !important;
    }
    .intel-chip-meme {
        background: rgba(188,140,255,0.1) !important;
        border: 1px solid rgba(188,140,255,0.25) !important;
        border-radius: 20px !important;
        padding: 3px 10px !important;
        color: #BC8CFF !important;
        font-size: 0.73rem !important;
    }
    /* 요약 텍스트 */
    .intel-summary {
        color: #CCCCCC !important;
        font-size: 0.85rem !important;
        line-height: 1.7 !important;
        border-left: 2px solid rgba(0,240,255,0.25) !important;
        padding-left: 12px !important;
        margin-top: 4px !important;
    }
    /* 수집 스탯 */
    .intel-stats {
        display: flex !important;
        gap: 10px !important;
        margin-top: 14px !important;
        padding-top: 12px !important;
        border-top: 1px solid rgba(255,255,255,0.06) !important;
    }
    .intel-stat-pill {
        background: rgba(255,255,255,0.04) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
        border-radius: 8px !important;
        padding: 4px 10px !important;
        color: #666 !important;
        font-size: 0.62rem !important;
        font-family: monospace !important;
    }
    .intel-stat-pill span { color: #AAAAAA !important; font-weight: 600 !important; }
    /* 로딩 플레이스홀더 */
    .intel-empty {
        text-align: center !important;
        padding: 40px 0 !important;
        color: #333 !important;
        font-size: 0.82rem !important;
    }
    /* INTEL 터미널 (수집 로그용) */
    .intel-terminal {
        background: #0A0A0A !important;
        border: 1px solid rgba(0,240,255,0.08) !important;
        border-radius: 10px !important;
        padding: 12px 14px !important;
        font-family: monospace !important;
        font-size: 0.72rem !important;
        color: #00C8FF !important;
        line-height: 1.55 !important;
        overflow-y: auto !important;
    }
    /* INTEL 실행 버튼 */
    .intel-run-btn > button {
        background: linear-gradient(135deg, #003D5C, #005580) !important;
        color: #00F0FF !important;
        border: 1px solid rgba(0,240,255,0.35) !important;
        border-radius: 12px !important;
        font-weight: 800 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        transition: all 0.2s !important;
    }
    .intel-run-btn > button:hover {
        background: linear-gradient(135deg, #005580, #0077AA) !important;
        box-shadow: 0 4px 18px rgba(0,240,255,0.25) !important;
        border-color: rgba(0,240,255,0.6) !important;
    }
    .intel-run-btn > button:disabled {
        background: #1A1A1A !important;
        color: #444 !important;
        border-color: rgba(255,255,255,0.08) !important;
        box-shadow: none !important;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════
def _init_state():
    defaults = {
        "brain_api_key":          os.getenv("GEMINI_API_KEY", ""),
        "swarm_log":              [],
        "swarm_preview_title":    "",
        "swarm_preview_content":  "",
        "swarm_wave_current":     0,
        "swarm_wave_total":       0,
        "posts_success":          0,
        "posts_failed":           0,
        "last_fired":             False,
        # ── 동시성 제어 (Flaw #1 수정) ──────────────
        "swarm_running":          False,   # 백그라운드 워커 실행 중 여부
        "swarm_queue":            None,    # 워커 → UI 메시지 채널
        "swarm_stop_event":       None,    # UI → 워커 중단 신호
        # ── INTEL 트렌드 분석 ────────────────────────
        "intel_running":          False,   # INTEL 워커 실행 중 여부
        "intel_queue":            None,    # INTEL 워커 → UI 채널
        "intel_log":              [],      # INTEL 수집/분석 로그
        "intel_result":           None,    # 마지막 분석 결과 dict
        # 15분 캐시: {cache_key → {"result": dict, "ts": float}}
        "intel_cache":            {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ══════════════════════════════════════════════
# 백그라운드 워커 — threading.Thread 기반
# ══════════════════════════════════════════════

def _interruptible_sleep(seconds: float, stop_event: threading.Event, interval: float = 0.5) -> None:
    """stop_event가 set되면 즉시 중단하는 분할 sleep.

    time.sleep(60~180)을 0.5초 단위로 쪼개어, 중단 신호를 빠르게 감지한다.
    """
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
    session_state에 직접 접근하지 않아 thread-safety를 보장한다.
    """

    def q_log(msg: str) -> None:
        log_q.put({"type": "log", "data": msg})

    def q_preview(title: str, content: str, wave: int, status: str) -> None:
        log_q.put({"type": "preview", "title": title, "content": content,
                   "wave": wave, "status": status})

    def q_stat(success: int = 0, fail: int = 0) -> None:
        log_q.put({"type": "stat", "success": success, "fail": fail})

    # ── Brain 초기화 ──
    try:
        brain = GhostBrain(api_key=api_key or None)
        database.init_db()
    except Exception as e:
        q_log(f"❌ Brain 초기화 실패: {str(e)[:120]}")
        log_q.put({"type": "done"})
        return

    # ══════════════════════════════════════════
    # Swarm Loop
    # ══════════════════════════════════════════
    for wave in range(1, wave_count + 1):
        if stop_ev.is_set():
            q_log("[SWARM] 🛑 중단 요청 — 루프 종료")
            break

        q_log(f"═══════ WAVE {wave}/{wave_count} ═══════")

        # ── 1) 생성 — 지수 백오프 재시도 (Flaw #2 수정) ──────────
        q_log(f"[W{wave}] 🧠 AI 작문 시작 → 주제: '{topic[:30]}'")
        q_preview("", "", wave, "GENERATING")

        gen_title: str | None = None
        gen_content: str = ""

        for attempt in range(3):
            if stop_ev.is_set():
                break
            try:
                result = brain.generate_post(
                    topic=topic,
                    gallery_id=gallery_id,
                    tone=tone,
                    context_hours=None,
                    length=length,
                )
                gen_title   = result.get("title", "무제")
                gen_content = result.get("content", "")
                q_log(f"[W{wave}] ✅ 생성 완료: '{gen_title[:30]}'")
                q_preview(gen_title, gen_content, wave, "GENERATED")
                break

            except RateLimitError:
                # 429: 지수 백오프 재시도 (60s → 120s → 포기)
                if attempt < 2:
                    backoff = 60 * (2 ** attempt)
                    q_log(
                        f"[W{wave}] ⚠️ Rate Limit (429) — {backoff}초 대기 후 재시도 "
                        f"({attempt + 1}/3)..."
                    )
                    _interruptible_sleep(backoff, stop_ev)
                else:
                    q_log(f"[W{wave}] ❌ Rate Limit 재시도 한도(3회) 초과 — WAVE {wave} 건너뜀")
                    gen_title = None

            except Exception as e:
                q_log(f"[W{wave}] ❌ 생성 실패: {str(e)[:80]}")
                gen_title = None
                break

        # 생성 실패 or 중단 요청 시 포스팅 단계 완전 건너뜀
        if not gen_title or stop_ev.is_set():
            continue

        # ── 2) 포스팅 ──────────────────────────────────────────────
        q_log(f"[W{wave}] 🚀 자동 포스팅 시작 → {gallery_type}/{gallery_id}")
        poster = GhostPoster(headless=headless, gallery_type=gallery_type)

        # 백그라운드 스레드 전용 이벤트 루프 생성
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            post_result = loop.run_until_complete(
                poster.auto_post(
                    gallery_id=gallery_id,
                    title=gen_title,
                    content=gen_content,
                    log_callback=q_log,
                )
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

        # ── 3) 대기 (마지막 WAVE 제외) ───────────────────────────
        if wave < wave_count and not stop_ev.is_set():
            wait_sec = random.randint(60, 180)
            q_log(f"[SWARM] ☕ 다음 WAVE까지 {wait_sec}초 대기...")
            _interruptible_sleep(wait_sec, stop_ev)

    q_log(f"═══════ SWARM COMPLETE — {wave_count} WAVES FIRED ═══════")
    log_q.put({"type": "done"})


# ══════════════════════════════════════════════
# INTEL 백그라운드 워커 — 수집 + 분석 파이프라인
# ══════════════════════════════════════════════

def _intel_worker(
    log_q: queue.Queue,
    *,
    api_key: str,
    gallery_id: str,
    gallery_type: str,
    pages: int,
) -> None:
    """백그라운드 스레드: TrendScraper 수집 → GhostBrain.analyze_trend() 분석.

    session_state에 직접 접근하지 않고 queue.Queue로만 UI에 통신한다.
    완료 시 {"type": "intel_result", "data": {...}} 메시지를 전송한다.
    """
    from ghost_protocol.scraper import TrendScraper
    from ghost_protocol.brain import GhostBrain, RateLimitError

    def _log(msg: str) -> None:
        log_q.put({"type": "intel_log", "data": msg})

    # ── Brain 초기화 ──────────────────────────────────────
    try:
        brain = GhostBrain(api_key=api_key or None)
    except Exception as e:
        _log(f"❌ Gemini 초기화 실패: {str(e)[:100]}")
        log_q.put({"type": "intel_done"})
        return

    # ── 1단계: AJAX 경량 수집 ─────────────────────────────
    _log(f"🔍 [{gallery_id}] 트렌드 수집 시작 (AJAX 모드, {pages} 페이지)")
    try:
        scraper  = TrendScraper()
        raw_data = scraper.collect_trending(
            gallery_id=gallery_id,
            gallery_type=gallery_type,
            pages=pages,
            progress_callback=_log,
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

    # ── 2단계: Gemini 트렌드 분석 ────────────────────────
    _log("🧠 Gemini 트렌드 분석 중...")
    try:
        result = brain.analyze_trend(raw_data)
        _log("✅ 분석 완료!")
        log_q.put({"type": "intel_result", "data": result})
    except RateLimitError:
        _log("⚠️ Rate Limit (429) — API 쿼터를 초과했습니다. 1분 후 재시도하세요.")
    except Exception as e:
        _log(f"❌ 분석 실패: {str(e)[:120]}")

    log_q.put({"type": "intel_done"})


# ══════════════════════════════════════════════
# Terminal HTML 렌더러
# ══════════════════════════════════════════════
def render_terminal(logs: list, height_px: int = 400) -> str:
    """실시간 로그를 어두운 터미널 스타일 HTML로 변환."""
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
# SIDEBAR — 타겟팅 설정
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        '<div class="sb-logo">👻 <span>GHOST</span> PROTOCOL</div>'
        '<div class="sb-sub">v5.0 · Launchpad</div>',
        unsafe_allow_html=True,
    )
    st.divider()

    # ── 타겟 설정 ──
    st.markdown('<div class="section-hdr">🎯 Target</div>', unsafe_allow_html=True)

    gallery_id = st.text_input(
        "Gallery ID",
        value="stockus",
        placeholder="예: stockus, universe, baseball_new9",
        help="DC Inside 갤러리 ID",
        label_visibility="visible",
    )

    # ── 갤러리 타입 선택 (명시적 렌더링) ──
    _type_map = {
        "마이너 (mgallery)": "mgallery",
        "정규 (board)":      "board",
        "미니 (mini)":       "mini",
    }
    _type_label = st.selectbox(
        "갤러리 타입",
        options=list(_type_map.keys()),
        index=0,
        help="정규 갤러리(예: universe)→ board / 마이너(예: stockus)→ mgallery",
    )
    gallery_type = _type_map[_type_label]

    st.divider()

    # ── 글 설정 ──
    st.markdown('<div class="section-hdr">✍️ Style</div>', unsafe_allow_html=True)

    tone_map = {
        "🧊 냉소적 (Cynical)":    "cynical",
        "😐 중립 (Neutral)":      "neutral",
        "📊 분석적 (Analytical)": "analytical",
        "🗣️ 독백 (Monologue)":   "monologue",
        "🔥 공격적 (Aggressive)": "aggressive",
        "💀 어그로성 (Aggro)":    "aggro",
    }
    tone_label = st.selectbox("Tone", options=list(tone_map.keys()), index=0)
    neural_tone = tone_map[tone_label]

    selected_length = st.selectbox(
        "Length",
        options=["아주 짧게 (1문장)", "짧게 (1~2문장)", "보통 (3~4문장)"],
        index=2,
    )

    headless = st.toggle("🕶️ Headless Mode", value=True, help="ON: 숨김 / OFF: 디버깅")

    st.divider()

    # ── API Key ──
    st.markdown('<div class="section-hdr">🔑 API Key</div>', unsafe_allow_html=True)
    _api_input = st.text_input(
        "Gemini API Key",
        type="password",
        value=st.session_state.brain_api_key,
        label_visibility="collapsed",
        placeholder="AIza...",
    )
    st.session_state.brain_api_key = _api_input
    _env_key = os.getenv("GEMINI_API_KEY", "")
    has_any_key = bool(st.session_state.brain_api_key or _env_key)
    if _env_key and not st.session_state.brain_api_key:
        st.caption("✅ .env 키 감지됨")

    st.divider()

    # ── 미션 스탯 ──
    st.markdown('<div class="section-hdr">📊 Mission Stats</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="stat-row">'
        f'<div class="stat-card stat-ok">'
        f'<div class="stat-val">{st.session_state.posts_success}</div>'
        f'<div class="stat-label">성공</div></div>'
        f'<div class="stat-card stat-err">'
        f'<div class="stat-val">{st.session_state.posts_failed}</div>'
        f'<div class="stat-label">실패</div></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.divider()
    if st.button("🔄 스탯 초기화", width="stretch"):
        st.session_state.posts_success = 0
        st.session_state.posts_failed = 0
        st.session_state.swarm_log = []
        st.session_state.swarm_preview_title = ""
        st.session_state.swarm_preview_content = ""
        st.rerun()


# ══════════════════════════════════════════════
# MAIN — Command Center (상단)
# ══════════════════════════════════════════════
st.markdown(
    '<div class="command-center">'
    '<div class="cc-header">'
    '<span class="cc-title">⚡ Command Center</span>'
    '<span class="cc-badge">SWARM MODE</span>'
    '</div>',
    unsafe_allow_html=True,
)

cc_left, cc_right = st.columns([3, 1], gap="large")

with cc_left:
    swarm_topic = st.text_input(
        "🎯 폭격할 주제를 입력하세요",
        placeholder="예: 나스닥 폭락 실화냐 / 테슬라 단타 계획 / 엔비디아 버블론",
        key="swarm_topic_input",
    )
    wave_count = st.slider(
        "💣 WAVE 횟수",
        min_value=1, max_value=10, value=3,
        help="연속 폭격 횟수. 각 WAVE 사이에 60~180초 랜덤 대기.",
    )

with cc_right:
    st.markdown(
        f'<div class="cc-target-info">'
        f'<div class="cti-row"><span class="cti-label">갤러리</span>'
        f'<span class="cti-val">{_html.escape(gallery_id)}</span></div>'
        f'<div class="cti-row"><span class="cti-label">타입</span>'
        f'<span class="cti-val">{gallery_type}</span></div>'
        f'<div class="cti-row"><span class="cti-label">톤</span>'
        f'<span class="cti-val">{neural_tone}</span></div>'
        f'<div class="cti-row"><span class="cti-label">길이</span>'
        f'<span class="cti-val">{selected_length.split(" ")[0]}</span></div>'
        f'<div class="cti-row"><span class="cti-label">Headless</span>'
        f'<span class="cti-val">{"ON" if headless else "OFF"}</span></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown('</div>', unsafe_allow_html=True)  # /command-center

# ══════════════════════════════════════════════
# FIRE / STOP 버튼
# ══════════════════════════════════════════════
_is_running = st.session_state.get("swarm_running", False)
_fire_disabled = not has_any_key or not (swarm_topic or "").strip() or _is_running

st.markdown('<div class="fire-btn">', unsafe_allow_html=True)
fire_clicked = st.button(
    "🔥  FIRE  —  폭격 개시" if not _is_running else "⏳  SWARM RUNNING...",
    width="stretch",
    type="primary",
    disabled=_fire_disabled or _is_running,
)
st.markdown('</div>', unsafe_allow_html=True)

# STOP 버튼 — 실행 중일 때만 표시
stop_clicked = False
if _is_running:
    stop_clicked = st.button("🛑  STOP  —  중단", width="stretch")

if not _is_running and _fire_disabled:
    if not has_any_key:
        st.caption("🔑 사이드바에 Gemini API Key를 입력하면 활성화됩니다.")
    elif not (swarm_topic or "").strip():
        st.caption("🎯 위에서 폭격할 주제를 입력하면 활성화됩니다.")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# MAIN — Live Terminal + Preview (하단)
# ══════════════════════════════════════════════
st.markdown("---")
col_preview, col_log = st.columns([3, 2], gap="medium")

with col_preview:
    st.markdown('<div class="section-hdr">🖥️ AI Post Preview</div>', unsafe_allow_html=True)
    _preview_ph = st.empty()

    if st.session_state.swarm_preview_title:
        _safe_t = _html.escape(st.session_state.swarm_preview_title)
        _safe_c = _html.escape(st.session_state.swarm_preview_content)
        _wave_lbl = (
            f"WAVE {st.session_state.swarm_wave_current}/"
            f"{st.session_state.swarm_wave_total} — POSTED"
            if st.session_state.last_fired else "LAST GENERATED"
        )
        _preview_ph.markdown(
            f'<div class="preview-dark">'
            f'<div class="pd-label">{_html.escape(_wave_lbl)}</div>'
            f'<div class="pd-title">{_safe_t}</div>'
            f'<div class="pd-body">{_safe_c}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        _preview_ph.markdown(
            '<div class="preview-dark">'
            '<div class="pd-empty">대기 중...<br><br>주제를 입력하고<br>🔥 FIRE를 눌러주세요.</div>'
            '</div>',
            unsafe_allow_html=True,
        )

with col_log:
    st.markdown('<div class="section-hdr">📟 Live Terminal</div>', unsafe_allow_html=True)
    _log_ph = st.empty()

    if st.session_state.swarm_log:
        _log_ph.markdown(render_terminal(st.session_state.swarm_log, height_px=420), unsafe_allow_html=True)
    else:
        _log_ph.markdown(
            '<div class="terminal" style="height:420px">'
            '<div style="color:#30363D;font-style:italic">'
            '// Ghost Protocol v5.0 Launchpad<br>'
            '// Terminal ready — awaiting launch sequence...'
            '</div></div>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# INTEL 브리핑 섹션 — Read-Only 트렌드 분석 (포스팅 없음)
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.markdown(
    '<div class="cc-header" style="margin-bottom:4px">'
    '<span class="cc-title">🔍 Intel 정보 브리핑</span>'
    '<span class="cc-badge">READ-ONLY · TREND ANALYSIS</span>'
    '</div>',
    unsafe_allow_html=True,
)

_intel_col_ctrl, _intel_col_result = st.columns([1, 2], gap="large")

# ── 컨트롤 패널 ────────────────────────────────────────────────
with _intel_col_ctrl:
    _intel_gid = st.text_input(
        "분석할 갤러리 ID",
        value="stockus",
        key="intel_gallery_id",
        placeholder="예: stockus, baseball_new9",
    )
    _intel_type_map = {
        "마이너 (mgallery)": "mgallery",
        "정규 (board)":      "board",
        "미니 (mini)":       "mini",
    }
    _intel_type_label = st.selectbox(
        "갤러리 타입",
        options=list(_intel_type_map.keys()),
        index=0,
        key="intel_gallery_type_label",
    )
    _intel_gtype = _intel_type_map[_intel_type_label]

    _intel_pages = st.slider(
        "수집 페이지 수",
        min_value=1, max_value=5, value=3,
        key="intel_pages",
        help="페이지 수가 많을수록 정확도↑, 수집 시간↑",
    )

    # ── 15분 캐시 유효성 확인 ──────────────────────────────
    _INTEL_CACHE_TTL = 15 * 60  # 900초
    _intel_cache_key = f"{_intel_gid}::{_intel_gtype}"
    _intel_cached    = st.session_state.intel_cache.get(_intel_cache_key)
    _intel_cache_age: float | None = None
    _intel_cache_valid = False

    if _intel_cached:
        _intel_cache_age   = time.time() - _intel_cached.get("ts", 0)
        _intel_cache_valid = _intel_cache_age < _INTEL_CACHE_TTL

    if _intel_cache_valid and _intel_cache_age is not None:
        _mins_ago = int(_intel_cache_age // 60)
        _secs_ago = int(_intel_cache_age % 60)
        st.caption(f"✅ 캐시 유효 — {_mins_ago}분 {_secs_ago}초 전 분석")
    elif _intel_cached:
        st.caption("♻️ 캐시 만료 (15분) — 재분석 필요")

    # ── 실행 버튼 ──────────────────────────────────────────
    _intel_is_running = st.session_state.get("intel_running", False)
    _intel_btn_disabled = (
        not has_any_key
        or not _intel_gid.strip()
        or _intel_is_running
    )

    st.markdown('<div class="intel-run-btn">', unsafe_allow_html=True)
    _intel_fire = st.button(
        "🔍  분석 시작" if not _intel_is_running else "⏳  분석 중...",
        key="intel_fire_btn",
        disabled=_intel_btn_disabled,
        width="stretch",
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # 수집 로그 미니 터미널
    if st.session_state.intel_log:
        _intel_log_html = "".join(
            f'<div>{_html.escape(ln)}</div>'
            for ln in st.session_state.intel_log[-20:]
        )
        st.markdown(
            f'<div class="intel-terminal" style="height:160px;overflow-y:auto">'
            f'{_intel_log_html}</div>',
            unsafe_allow_html=True,
        )

# ── 결과 패널 ────────────────────────────────────────────────
with _intel_col_result:
    _ir = st.session_state.intel_result

    # 캐시 히트 시 캐시 결과 표시
    if _ir is None and _intel_cache_valid and _intel_cached:
        _ir = _intel_cached["result"]

    if _ir:
        # 감성 → CSS 클래스 매핑
        _SENTIMENT_CLASS = {
            "패닉": "panic", "공포": "panic",
            "적대적": "hostile", "분노": "hostile", "공격": "hostile",
            "조롱": "mock", "냉소": "mock", "비꼬": "mock",
            "우호적": "friendly", "긍정": "friendly",
        }
        _sent_raw = _ir.get("sentiment", "알 수 없음")
        _sent_cls = "intel-sentiment-neutral"
        for kw, cls in _SENTIMENT_CLASS.items():
            if kw in _sent_raw:
                _sent_cls = f"intel-sentiment-{cls}"
                break

        # ── 캐시 타임스탬프 표시 ──
        _ts_label = ""
        if _intel_cache_valid and _intel_cache_age is not None:
            _ts_label = f"캐시 {int(_intel_cache_age // 60)}분 {int(_intel_cache_age % 60)}초 전"

        _hot_chips = "".join(
            f'<span class="intel-chip-hot">{_html.escape(t)}</span>'
            for t in _ir.get("hot_topics", [])
        )
        _meme_chips = "".join(
            f'<span class="intel-chip-meme">{_html.escape(m)}</span>'
            for m in _ir.get("memes", [])
        )
        _kw_chips = "".join(
            f'<span class="intel-chip-kw">{_html.escape(w)}</span>'
            for w in _ir.get("top_keywords", [])[:15]
        )
        _stats = _ir.get("stats", {})
        _stat_pills = (
            f'<span class="intel-stat-pill">제목 <span>{_stats.get("titles_count", 0)}</span>개</span>'
            f'<span class="intel-stat-pill">댓글 <span>{_stats.get("comments_count", 0)}</span>개</span>'
            f'<span class="intel-stat-pill">키워드 <span>{_stats.get("keywords_found", 0)}</span>개</span>'
        )

        st.markdown(
            f'<div class="intel-card">'
            f'  <div class="intel-header">'
            f'    <span class="intel-title">📡 INTEL BRIEFING</span>'
            f'    <span class="intel-gallery-badge">{_html.escape(_intel_gid)} / {_intel_gtype}</span>'
            f'    <span class="intel-cache-ts">{_html.escape(_ts_label)}</span>'
            f'  </div>'
            # 감성
            f'  <div class="intel-section-label">OVERALL SENTIMENT</div>'
            f'  <div class="intel-sentiment {_sent_cls}">{_html.escape(_sent_raw)}</div>'
            # 핫 떡밥
            f'  <div class="intel-section-label">🔥 HOT TOPICS</div>'
            f'  <div class="intel-chips">{_hot_chips}</div>'
            # 밈
            f'  <div class="intel-section-label">💬 TRENDING MEMES</div>'
            f'  <div class="intel-chips">{_meme_chips if _meme_chips else "<span style=\"color:#333;font-size:0.72rem\">감지된 밈 없음</span>"}</div>'
            # 요약
            f'  <div class="intel-section-label">📝 SUMMARY</div>'
            f'  <div class="intel-summary">{_html.escape(_ir.get("summary", ""))}</div>'
            # 키워드 클라우드
            f'  <div class="intel-section-label" style="margin-top:14px">🔑 TOP KEYWORDS</div>'
            f'  <div class="intel-chips">{_kw_chips}</div>'
            # 수집 스탯
            f'  <div class="intel-stats">{_stat_pills}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="intel-card">'
            '<div class="intel-empty">'
            '📡 대기 중<br><br>'
            '갤러리 ID를 확인하고<br>'
            '<b style="color:#00F0FF">🔍 분석 시작</b>을 누르세요.<br><br>'
            '<span style="color:#333;font-size:0.72rem">분석 결과는 15분간 캐시됩니다.</span>'
            '</div>'
            '</div>',
            unsafe_allow_html=True,
        )

# ══════════════════════════════════════════════
# FIRE — 백그라운드 워커 시작
# ══════════════════════════════════════════════
if fire_clicked:
    _topic = (swarm_topic or "").strip()

    if not has_any_key:
        st.error("⚠️ Gemini API Key가 없습니다. 사이드바에 입력하세요.")
    elif not _topic:
        st.error("⚠️ 주제를 입력하세요.")
    else:
        try:
            _accounts = load_accounts()
        except (FileNotFoundError, ValueError) as _e:
            st.error(f"⚠️ accounts.json 로드 실패: {str(_e)}")
            _accounts = None

        if _accounts:
            # ── 상태 초기화 ──
            st.session_state.swarm_log = []
            st.session_state.swarm_preview_title = ""
            st.session_state.swarm_preview_content = ""
            st.session_state.swarm_wave_total = wave_count
            st.session_state.swarm_wave_current = 0
            st.session_state.last_fired = True
            st.session_state.swarm_running = True

            # ── 통신 원시 타입 생성 ──
            _log_q: queue.Queue = queue.Queue()
            _stop_ev: threading.Event = threading.Event()
            st.session_state.swarm_queue = _log_q
            st.session_state.swarm_stop_event = _stop_ev

            # ── 백그라운드 워커 시작 ──
            threading.Thread(
                target=_swarm_worker,
                kwargs={
                    "log_q":       _log_q,
                    "stop_ev":     _stop_ev,
                    "api_key":     st.session_state.brain_api_key,
                    "topic":       _topic,
                    "wave_count":  wave_count,
                    "gallery_id":  gallery_id,
                    "gallery_type": gallery_type,
                    "tone":        neural_tone,
                    "length":      selected_length,
                    "headless":    headless,
                },
                daemon=True,
            ).start()

            st.rerun()  # 즉시 폴링 모드 진입

# ── STOP 처리 ──
if stop_clicked and st.session_state.get("swarm_stop_event"):
    st.session_state.swarm_stop_event.set()
    st.session_state.swarm_log.append("[SWARM] 🛑 중단 요청 전송됨 — 현재 작업 완료 후 종료...")

# ══════════════════════════════════════════════
# INTEL FIRE — 분석 워커 시작
# ══════════════════════════════════════════════
if _intel_fire:
    _igid = (_intel_gid or "").strip()
    if not has_any_key:
        st.error("⚠️ Gemini API Key가 없습니다. 사이드바에 입력하세요.")
    elif not _igid:
        st.error("⚠️ 갤러리 ID를 입력하세요.")
    elif _intel_cache_valid and _intel_cached:
        # 15분 캐시 히트 → 워커 없이 캐시 결과 즉시 표시
        st.session_state.intel_result = _intel_cached["result"]
        st.rerun()
    else:
        # 캐시 미스 / 만료 → 백그라운드 워커 실행
        st.session_state.intel_log    = []
        st.session_state.intel_result = None
        st.session_state.intel_running = True

        _intel_q: queue.Queue = queue.Queue()
        st.session_state.intel_queue = _intel_q

        threading.Thread(
            target=_intel_worker,
            kwargs={
                "log_q":       _intel_q,
                "api_key":     st.session_state.brain_api_key,
                "gallery_id":  _igid,
                "gallery_type": _intel_gtype,
                "pages":       _intel_pages,
            },
            daemon=True,
        ).start()

        st.rerun()


# ══════════════════════════════════════════════
# POLLING — Swarm + INTEL 백그라운드 스레드 → UI 동기화
# ══════════════════════════════════════════════
# 매 rerun마다 양 Queue를 드레인하고 session_state를 갱신.
# 어느 한 워커라도 실행 중이면 0.5초 폴링 간격을 유지한다.
# 메인 스레드 최대 블로킹 시간: 0.5초 — WebSocket 타임아웃 위험 없음.
_any_running = False
_any_done    = False

# ── Swarm Queue 드레인 ─────────────────────────────────
if st.session_state.get("swarm_running") and st.session_state.get("swarm_queue") is not None:
    _any_running = True
    _sq: queue.Queue = st.session_state.swarm_queue

    while True:
        try:
            _msg = _sq.get_nowait()
        except queue.Empty:
            break

        if _msg["type"] == "log":
            st.session_state.swarm_log.append(_msg["data"])

        elif _msg["type"] == "preview":
            st.session_state.swarm_preview_title   = _msg["title"]
            st.session_state.swarm_preview_content = _msg["content"]
            st.session_state.swarm_wave_current     = _msg["wave"]

        elif _msg["type"] == "stat":
            st.session_state.posts_success += _msg.get("success", 0)
            st.session_state.posts_failed  += _msg.get("fail", 0)

        elif _msg["type"] == "done":
            st.session_state.swarm_running    = False
            st.session_state.swarm_queue      = None
            st.session_state.swarm_stop_event = None
            _any_running = False
            _any_done    = True

# ── INTEL Queue 드레인 ─────────────────────────────────
if st.session_state.get("intel_running") and st.session_state.get("intel_queue") is not None:
    _any_running = True
    _iq: queue.Queue = st.session_state.intel_queue

    while True:
        try:
            _imsg = _iq.get_nowait()
        except queue.Empty:
            break

        if _imsg["type"] == "intel_log":
            st.session_state.intel_log.append(_imsg["data"])

        elif _imsg["type"] == "intel_result":
            _result_data = _imsg["data"]
            st.session_state.intel_result = _result_data
            # 15분 캐시 갱신
            _ck = f"{st.session_state.get('intel_gallery_id', '')}::{_intel_gtype}"
            st.session_state.intel_cache[_ck] = {
                "result": _result_data,
                "ts":     time.time(),
            }

        elif _imsg["type"] == "intel_done":
            st.session_state.intel_running = False
            st.session_state.intel_queue   = None
            _any_running = False
            _any_done    = True

# ── 폴링 제어 ─────────────────────────────────────────
if _any_running:
    time.sleep(0.5)
    st.rerun()
elif _any_done:
    st.rerun()
