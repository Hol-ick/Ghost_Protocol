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
    /* ═══ 1. 전역 다크 베이스 ═══ */
    .stApp, .stMain, footer {
        background-color: #0E1117 !important;
        color: #FAFAFA !important;
    }
    .stApp header[data-testid="stHeader"] {
        background-color: #0E1117 !important;
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
# POLLING — 백그라운드 스레드 → UI 동기화
# ══════════════════════════════════════════════
# 매 rerun마다 Queue를 드레인하고 session_state를 갱신.
# swarm_running이 True인 동안 0.5초 폴링 간격으로 st.rerun()을 유지한다.
# 메인 스레드의 최대 블로킹 시간: 0.5초 — WebSocket 타임아웃 위험 없음.
if st.session_state.get("swarm_running") and st.session_state.get("swarm_queue") is not None:
    _q: queue.Queue = st.session_state.swarm_queue
    _done = False

    # 큐에 쌓인 메시지 전부 드레인
    while True:
        try:
            _msg = _q.get_nowait()
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
            _done = True

    # 실행 중: 0.5초 후 재폴링 / 완료: 최종 rerun으로 UI 확정
    if st.session_state.swarm_running:
        time.sleep(0.5)
        st.rerun()
    elif _done:
        st.rerun()
