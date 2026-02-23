"""Ghost Protocol v5.0 — LAUNCHPAD

Pipeline (Swarm Mode): TOPIC → GENERATE → POST
스캔 단계 없음 — 주제 직접 입력 후 즉시 폭격.

실행: streamlit run app.py
"""

import asyncio
import html as _html
import os
import random
import sys
import time

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import streamlit as st

from ghost_protocol import database
from ghost_protocol.brain import GhostBrain
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
# CSS — Warm Sidebar + Dark Command Center
# ══════════════════════════════════════════════
st.markdown("""
<style>
    /* ═══ 1. 기본 라이트 테마 강제 ═══ */
    :root, [data-theme="dark"] {
        --primary-color:            #C8A97E !important;
        --background-color:         #F4F2EE !important;
        --secondary-background-color: #FFFFFF !important;
        --text-color:               #2C2C2C !important;
        color-scheme: light !important;
    }
    .stApp, .stMain, footer {
        background-color: var(--background-color) !important;
        color: var(--text-color) !important;
    }
    .stApp header[data-testid="stHeader"] {
        background-color: var(--background-color) !important;
    }
    .stMainBlockContainer { padding-top: 1.5rem !important; }

    /* ═══ 2. 사이드바 ═══ */
    section[data-testid="stSidebar"] > div {
        background-color: #FFFFFF !important;
        box-shadow: 2px 0 12px rgba(0,0,0,0.04) !important;
    }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p { color: #2C2C2C !important; }

    /* ═══ 3. 사이드바 로고 ═══ */
    .sb-logo {
        text-align: center !important;
        font-size: 1.1rem !important;
        font-weight: 900 !important;
        letter-spacing: 3px !important;
        color: #2C2C2C !important;
        padding: 8px 0 4px 0 !important;
    }
    .sb-logo span { color: #C8A97E !important; }
    .sb-sub {
        text-align: center !important;
        font-size: 0.68rem !important;
        color: #B0A898 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        margin-bottom: 4px !important;
    }

    /* ═══ 4. 입력 필드 기본 ═══ */
    div[data-baseweb="input"] {
        background-color: #FFFFFF !important;
        border: 1px solid #DDD8CF !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: #C8A97E !important;
        box-shadow: 0 0 0 2px rgba(200,169,126,0.15) !important;
    }
    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] input {
        background-color: #FFFFFF !important;
        color: #2C2C2C !important;
        -webkit-text-fill-color: #2C2C2C !important;
    }
    ul[role="listbox"] { background-color: #FFFFFF !important; }
    li[role="option"] { color: #2C2C2C !important; }
    li[role="option"]:hover, li[role="option"][aria-selected="true"] {
        background-color: #F2EFE9 !important; color: #C8A97E !important;
    }
    div[data-baseweb="popover"], div[data-baseweb="popover"] > div {
        background-color: #FFFFFF !important;
    }
    .stTextInput input, .stTextArea textarea {
        background-color: #FFFFFF !important; color: #2C2C2C !important;
    }

    /* ═══ 5. 버튼 기본 (골드) ═══ */
    div.stButton > button {
        background-color: #C8A97E !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 12px !important;
        font-weight: 700 !important;
        transition: all 0.2s !important;
    }
    div.stButton > button:hover {
        background-color: #B08D5B !important;
        box-shadow: 0 4px 14px rgba(200,169,126,0.4) !important;
    }

    /* ═══ 6. Command Center 카드 ═══ */
    .command-center {
        background: linear-gradient(145deg, #12121E 0%, #1A1A2E 100%) !important;
        border: 1px solid #2E2E4A !important;
        border-radius: 18px !important;
        padding: 28px 32px !important;
        margin-bottom: 18px !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.2) !important;
    }
    .cc-header {
        display: flex !important;
        align-items: center !important;
        gap: 10px !important;
        margin-bottom: 20px !important;
    }
    .cc-title {
        color: #E0DFFF !important;
        font-size: 0.75rem !important;
        font-weight: 800 !important;
        letter-spacing: 4px !important;
        text-transform: uppercase !important;
    }
    .cc-badge {
        background: rgba(188, 140, 255, 0.12) !important;
        border: 1px solid rgba(188, 140, 255, 0.3) !important;
        border-radius: 20px !important;
        padding: 2px 10px !important;
        color: #BC8CFF !important;
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
    .cti-label { color: #484F58 !important; font-size: 0.68rem !important; letter-spacing: 1px !important; text-transform: uppercase !important; }
    .cti-val { color: #C8D3E0 !important; font-size: 0.78rem !important; font-weight: 600 !important; font-family: monospace !important; }
    /* Command Center 내부 입력 필드 다크 오버라이드 */
    .command-center .stTextInput input,
    .command-center input[type="text"] {
        background-color: rgba(255,255,255,0.06) !important;
        color: #E6EDF3 !important;
        -webkit-text-fill-color: #E6EDF3 !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
        border-radius: 8px !important;
    }
    .command-center label { color: #8B949E !important; }

    /* ═══ 7. FIRE 버튼 ═══ */
    .fire-btn > button {
        background: linear-gradient(135deg, #E53935 0%, #B71C1C 100%) !important;
        color: #FFFFFF !important;
        font-size: 1.05rem !important;
        font-weight: 900 !important;
        letter-spacing: 4px !important;
        text-transform: uppercase !important;
        padding: 0.85rem 2rem !important;
        border-radius: 14px !important;
        border: none !important;
        box-shadow: 0 6px 24px rgba(229, 57, 53, 0.45) !important;
        transition: all 0.2s !important;
    }
    .fire-btn > button:hover {
        background: linear-gradient(135deg, #EF5350 0%, #C62828 100%) !important;
        box-shadow: 0 8px 32px rgba(229, 57, 53, 0.65) !important;
        transform: translateY(-2px) !important;
    }
    .fire-btn > button:disabled {
        background: #3D3D3D !important;
        box-shadow: none !important;
        transform: none !important;
        opacity: 0.5 !important;
    }

    /* ═══ 8. Live Terminal (dark log) ═══ */
    .terminal {
        background: #0D1117 !important;
        border: 1px solid #21262D !important;
        border-radius: 12px !important;
        padding: 16px !important;
        overflow-y: auto !important;
        font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
        font-size: 0.76rem !important;
        line-height: 1.6 !important;
        color: #8B949E !important;
    }
    .terminal div { padding: 1px 0 !important; }
    .t-ok   { color: #3FB950 !important; }
    .t-err  { color: #F85149 !important; font-weight: 600 !important; }
    .t-info { color: #58A6FF !important; }
    .t-warn { color: #D29922 !important; }
    .t-wave { color: #BC8CFF !important; font-weight: 700 !important; letter-spacing: 1px !important; }

    /* ═══ 9. Preview 카드 (dark) ═══ */
    .preview-dark {
        background: #161B22 !important;
        border: 1px solid #30363D !important;
        border-radius: 14px !important;
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
        color: #E6EDF3 !important;
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        margin-bottom: 14px !important;
        padding-bottom: 12px !important;
        border-bottom: 1px solid #30363D !important;
        line-height: 1.4 !important;
    }
    .pd-body {
        color: #8B949E !important;
        font-size: 0.9rem !important;
        line-height: 1.75 !important;
        white-space: pre-wrap !important;
    }
    .pd-empty {
        color: #30363D !important;
        font-style: italic !important;
        text-align: center !important;
        padding: 60px 0 !important;
        font-size: 0.85rem !important;
    }
    .pd-status {
        color: #3FB950 !important;
        font-size: 0.65rem !important;
        font-weight: 600 !important;
        letter-spacing: 2px !important;
        text-transform: uppercase !important;
        margin-top: 14px !important;
        padding-top: 10px !important;
        border-top: 1px solid #21262D !important;
    }

    /* ═══ 10. 섹션 헤더 ═══ */
    .section-hdr {
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        letter-spacing: 2.5px !important;
        text-transform: uppercase !important;
        color: #8C8478 !important;
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
        background: #F7F5F0 !important;
        border: 1px solid #E8E2D8 !important;
        border-radius: 10px !important;
        padding: 10px 8px !important;
        text-align: center !important;
    }
    .stat-val { font-size: 1.4rem !important; font-weight: 800 !important; color: #2C2C2C !important; }
    .stat-label { font-size: 0.62rem !important; color: #8C8478 !important; text-transform: uppercase !important; letter-spacing: 1px !important; }
    .stat-ok .stat-val { color: #3a7d44 !important; }
    .stat-err .stat-val { color: #C0392B !important; }

    /* ═══ 12. Progress Bar ═══ */
    .stProgress > div > div {
        background: linear-gradient(90deg, #E53935, #BC8CFF) !important;
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
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


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

# ── FIRE 버튼 ──
_fire_disabled = not has_any_key or not (swarm_topic or "").strip()

st.markdown('<div class="fire-btn">', unsafe_allow_html=True)
fire_clicked = st.button(
    "🔥  FIRE  —  폭격 개시",
    width="stretch",
    type="primary",
    disabled=_fire_disabled,
)
st.markdown('</div>', unsafe_allow_html=True)

if _fire_disabled:
    if not has_any_key:
        st.caption("🔑 사이드바에 Gemini API Key를 입력하면 활성화됩니다.")
    elif not (swarm_topic or "").strip():
        st.caption("🎯 위에서 폭격할 주제를 입력하면 활성화됩니다.")

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════
# MAIN — Live Terminal (하단)
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
# FIRE 실행 로직
# ══════════════════════════════════════════════
if fire_clicked:
    _topic = (swarm_topic or "").strip()

    if not has_any_key:
        st.error("⚠️ Gemini API Key가 없습니다. 사이드바에 입력하세요.")
    elif not _topic:
        st.error("⚠️ 주제를 입력하세요.")
    else:
        # 계정 파일 확인
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

            # ── 로그 + 프리뷰 실시간 업데이트 헬퍼 ──
            def _slog(msg: str):
                st.session_state.swarm_log.append(msg)
                _log_ph.markdown(
                    render_terminal(st.session_state.swarm_log, height_px=420),
                    unsafe_allow_html=True,
                )

            def _update_preview(title: str, content: str, wave: int, status: str = "GENERATING"):
                st.session_state.swarm_preview_title = title
                st.session_state.swarm_preview_content = content
                st.session_state.swarm_wave_current = wave
                _safe_t = _html.escape(title) if title else ""
                _safe_c = _html.escape(content) if content else ""
                _lbl = _html.escape(f"WAVE {wave}/{wave_count} — {status}")
                if title:
                    _preview_ph.markdown(
                        f'<div class="preview-dark">'
                        f'<div class="pd-label">{_lbl}</div>'
                        f'<div class="pd-title">{_safe_t}</div>'
                        f'<div class="pd-body">{_safe_c}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    _preview_ph.markdown(
                        f'<div class="preview-dark">'
                        f'<div class="pd-label">{_lbl}</div>'
                        f'<div class="pd-empty">🧠 AI 작문 중...</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # ── GhostBrain 초기화 ──
            try:
                _brain = GhostBrain(api_key=st.session_state.brain_api_key or None)
                database.init_db()
            except Exception as _e:
                st.error(f"⚠️ Brain 초기화 실패: {str(_e)[:120]}")
                st.stop()

            # ══════════════════════════════════════════
            # SWARM LOOP — 스캔 없음, 즉시 작문 → 포스팅
            # ══════════════════════════════════════════
            for _wave in range(1, wave_count + 1):
                _slog(f"═══════ WAVE {_wave}/{wave_count} ═══════")

                # ── 1) 작문 (Generate) ──
                _slog(f"[W{_wave}] 🧠 AI 작문 시작 → 주제: '{_topic[:30]}'")
                _update_preview("", "", _wave, "GENERATING")

                try:
                    _result = _brain.generate_post(
                        topic=_topic,
                        gallery_id=gallery_id,
                        tone=neural_tone,
                        context_hours=None,
                        length=selected_length,
                    )
                    _gen_title   = _result.get("title", "무제")
                    _gen_content = _result.get("content", "")
                    _slog(f"[W{_wave}] ✅ 생성 완료: '{_gen_title[:30]}'")
                    _update_preview(_gen_title, _gen_content, _wave, "GENERATED")

                except Exception as _e:
                    _slog(f"[W{_wave}] ❌ 생성 실패: {str(_e)[:80]}")
                    continue

                # ── 2) 포스팅 (Post) ──
                _slog(f"[W{_wave}] 🚀 자동 포스팅 시작 → {gallery_type}/{gallery_id}")
                _poster = GhostPoster(headless=headless, gallery_type=gallery_type)
                _post_loop = asyncio.new_event_loop()
                try:
                    _post_result = _post_loop.run_until_complete(
                        _poster.auto_post(
                            gallery_id=gallery_id,
                            title=_gen_title,
                            content=_gen_content,
                            log_callback=_slog,
                        )
                    )
                finally:
                    _post_loop.close()

                if _post_result["success"]:
                    st.session_state.posts_success += 1
                    _slog(f"[W{_wave}] 🎉 포스팅 성공! ({_post_result['message']})")
                    _update_preview(_gen_title, _gen_content, _wave, "✅ POSTED")
                else:
                    st.session_state.posts_failed += 1
                    _slog(f"[W{_wave}] ❌ 포스팅 실패: {_post_result['message']}")
                    _update_preview(_gen_title, _gen_content, _wave, "❌ FAILED")

                # ── 3) 대기 (마지막 WAVE 제외) ──
                if _wave < wave_count:
                    _wait_sec = random.randint(60, 180)
                    _slog(f"[SWARM] ☕ 다음 WAVE까지 {_wait_sec}초 대기...")
                    time.sleep(_wait_sec)

            # ── 완료 ──
            _slog(f"═══════ SWARM COMPLETE — {wave_count} WAVES FIRED ═══════")
            st.rerun()
