"""Ghost Protocol v5.0 — Warm Bento Dashboard + Swarm Mode.

One-Page Pipeline: SCAN → GENERATE → POST
Warm Bento UI + .streamlit/config.toml 테마 강제.

실행: streamlit run app.py
"""

import asyncio
import html as _html
import os
import random
import sys
import re
import threading
import time
from collections import Counter

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx

from ghost_protocol import database
from ghost_protocol.brain import GhostBrain
from ghost_protocol.config import KEYWORD_STOPWORDS
from ghost_protocol.poster import GhostPoster, load_accounts
from ghost_protocol.scraper import GalleryScraper

# ══════════════════════════════════════════════
# Page Config
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="Ghost Protocol",
    page_icon="👻",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════
# Nuclear CSS — 다크 모드 완전 차단 + 웜 벤토 강제
# (.streamlit/config.toml과 함께 이중 방어)
# ══════════════════════════════════════════════
st.markdown("""
<style>
    /* ═══ 1. 다크 모드 변수 무력화 & 라이트 테마 변수 강제 ═══ */
    :root, [data-theme="dark"] {
        --primary-color: #C8A97E !important;
        --background-color: #FBF9F6 !important;
        --secondary-background-color: #FFFFFF !important;
        --text-color: #2C2C2C !important;
        --font: "sans serif" !important;
        color-scheme: light !important;
    }

    /* ═══ 2. 최상위 컨테이너 배경색 강제 (다크 모드 침투 차단) ═══ */
    .stApp, .stMain, .stSidebar,
    div[data-testid="stDecoration"], footer {
        background-color: var(--background-color) !important;
        color: var(--text-color) !important;
    }
    .stApp header[data-testid="stHeader"] {
        background-color: var(--background-color) !important;
    }
    .stMainBlockContainer {
        padding-top: 2rem !important;
    }

    /* ═══ 3. 사이드바 배경 & 텍스트 강제 ═══ */
    section[data-testid="stSidebar"] > div {
        background-color: var(--secondary-background-color) !important;
        box-shadow: 2px 0 12px rgba(0,0,0,0.03) !important;
    }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] label {
        color: var(--text-color) !important;
    }

    /* ═══ 4. 텍스트 & 헤더 색상 강제 ═══ */
    h1, h2, h3, h4, h5, h6, p, li, span,
    div.stMarkdown, .stText {
        color: var(--text-color) !important;
    }

    /* ═══ 5. Bento Box ═══ */
    .bento {
        background: var(--secondary-background-color) !important;
        border: none !important;
        border-radius: 16px !important;
        padding: 24px !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.06) !important;
        margin-bottom: 16px !important;
    }

    /* ═══ 6. Metric Card ═══ */
    .metric-card {
        background: var(--secondary-background-color) !important;
        border: none !important;
        border-radius: 16px !important;
        padding: 20px 24px !important;
        text-align: center !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.06) !important;
    }
    .metric-card .mc-label {
        color: #8C8478 !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 1.5px !important;
        margin-bottom: 6px !important;
    }
    .metric-card .mc-value {
        color: var(--text-color) !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
        font-family: 'Inter', -apple-system, sans-serif !important;
    }
    .metric-card .mc-icon {
        font-size: 1.4rem !important;
        margin-bottom: 4px !important;
    }

    /* ═══ 7. Step Header ═══ */
    .step-hdr {
        font-weight: 700 !important;
        font-size: 0.82rem !important;
        text-transform: uppercase !important;
        letter-spacing: 1.5px !important;
        padding: 8px 14px !important;
        border-radius: 10px !important;
        display: inline-block !important;
        margin-bottom: 14px !important;
    }
    .step-hdr-scan { background: rgba(107,122,100,0.1) !important; color: #6B7A64 !important; }
    .step-hdr-brain { background: rgba(200,169,126,0.12) !important; color: #C8A97E !important; }
    .step-hdr-post { background: rgba(107,122,100,0.1) !important; color: #6B7A64 !important; }
    .step-hdr-log { background: rgba(200,169,126,0.1) !important; color: #C8A97E !important; }

    /* ═══ 8. Keyword Tag ═══ */
    .kw-tag {
        display: inline-block !important;
        background: rgba(107,122,100,0.08) !important;
        border: 1px solid rgba(107,122,100,0.2) !important;
        border-radius: 20px !important;
        padding: 4px 14px !important;
        margin: 3px !important;
        font-size: 0.8rem !important;
        color: #6B7A64 !important;
        font-weight: 500 !important;
    }
    .kw-tag-hot {
        border-color: rgba(200,169,126,0.5) !important;
        color: #C8A97E !important;
        background: rgba(200,169,126,0.08) !important;
    }

    /* ═══ 9. 로그 영역 ═══ */
    .log-box {
        background: #FAF9F7 !important;
        border: 1px solid #E5E0D8 !important;
        border-radius: 12px !important;
        padding: 14px !important;
        overflow-y: auto !important;
        font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
        font-size: 0.78rem !important;
        line-height: 1.5 !important;
    }
    .log-line { color: #8C8478 !important; }
    .log-error { color: #C0392B !important; font-weight: 600 !important; }
    .log-info { color: #5B7FAF !important; }
    .log-ok { color: #6B7A64 !important; }
    .log-worker { color: #C8A97E !important; }

    /* ═══ 10. 버튼 (골드 테마) ═══ */
    div.stButton > button {
        background-color: var(--primary-color) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 12px !important;
        font-weight: 600 !important;
        padding: 0.6rem 1.2rem !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button:hover {
        background-color: #B08D5B !important;
        box-shadow: 0 4px 12px rgba(200,169,126,0.4) !important;
    }
    div.stButton > button[kind="secondary"] {
        background-color: #E0E0E0 !important;
        color: #555555 !important;
    }

    /* ═══ 11. 입력 필드 & 셀렉트 ═══ */
    div[data-baseweb="input"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E0E0E0 !important;
        border-radius: 8px !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: var(--primary-color) !important;
        box-shadow: 0 0 0 2px rgba(200,169,126,0.2) !important;
    }
    div[data-baseweb="select"] > div {
        background-color: #FFFFFF !important;
        border-radius: 8px !important;
    }
    .stTextInput input, .stTextArea textarea {
        background-color: #FFFFFF !important;
        color: var(--text-color) !important;
    }

    /* ═══ 12. Preview Card ═══ */
    .preview-card {
        background: #FAF9F7 !important;
        border: 1px solid #E5E0D8 !important;
        border-radius: 14px !important;
        padding: 20px !important;
    }
    .preview-label {
        color: #C8A97E !important;
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 2px !important;
        margin-bottom: 10px !important;
    }
    .preview-title {
        color: var(--text-color) !important;
        font-size: 1.1rem !important;
        font-weight: 700 !important;
        margin-bottom: 12px !important;
        padding-bottom: 10px !important;
        border-bottom: 1px solid #E5E0D8 !important;
    }
    .preview-body {
        color: #5A5A5A !important;
        font-size: 0.92rem !important;
        line-height: 1.75 !important;
        white-space: pre-wrap !important;
    }

    /* ═══ 13. Sidebar Title ═══ */
    .sidebar-title {
        text-align: center !important;
        font-size: 1.25rem !important;
        font-weight: 800 !important;
        color: var(--text-color) !important;
        letter-spacing: 1px !important;
        padding-bottom: 10px !important;
        margin-bottom: 16px !important;
        border-bottom: 1px solid #E5E0D8 !important;
    }
    .sidebar-title span { color: #6B7A64 !important; }

    /* ═══ 14. Progress Bar (골드 그라데이션) ═══ */
    div[data-baseweb="progress-bar"] > div {
        background-color: #E0E0E0 !important;
    }
    div[data-baseweb="progress-bar"] > div > div {
        background: linear-gradient(90deg, var(--primary-color), #D4B68F) !important;
    }
    .stProgress > div > div {
        background: linear-gradient(90deg, #C8A97E, #D4B88E) !important;
    }

    /* ═══ 15. Expander & 기타 ═══ */
    details summary {
        color: var(--text-color) !important;
    }
    div[data-testid="stExpander"] {
        background-color: var(--secondary-background-color) !important;
        border-radius: 12px !important;
        border: 1px solid #E5E0D8 !important;
    }

    /* ═══ 16. 입력창·드롭다운·리스트박스 다크모드 잔재 강제 라이트화 ═══ */
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div,
    ul[role="listbox"] {
        background-color: #FFFFFF !important;
        color: #2C2C2C !important;
    }
    div[data-baseweb="base-input"] input {
        color: #2C2C2C !important;
        -webkit-text-fill-color: #2C2C2C !important;
    }

    /* ═══ 17. Expander 내부 버튼·텍스트 강제 라이트화 ═══ */
    div[data-testid="stExpander"] div[role="button"] p {
        color: #2C2C2C !important;
    }

    /* ═══ 18. Selectbox 드롭다운 Popover 강제 라이트화 ═══ */
    div[data-baseweb="popover"], div[data-baseweb="popover"] > div {
        background-color: #FFFFFF !important;
    }
    ul[role="listbox"] {
        background-color: #FFFFFF !important;
    }
    li[role="option"] {
        color: #2C2C2C !important;
        background-color: transparent !important;
    }
    li[role="option"]:hover, li[role="option"][aria-selected="true"] {
        background-color: #F2EFE9 !important;
        color: #C8A97E !important;
    }

    /* ═══ 19. Latest Updates Feed (우측 실시간 로그 패널) ═══ */
    .latest-feed {
        overflow-y: auto !important;
        font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
        font-size: 0.72rem !important;
        line-height: 1.55 !important;
        color: #8C8478 !important;
        background: #FAF9F7 !important;
        border: 1px solid #E5E0D8 !important;
        border-radius: 10px !important;
        padding: 10px 12px !important;
    }
    .feed-item {
        padding: 5px 2px !important;
        border-bottom: 1px solid #F0EDE8 !important;
        word-break: break-word !important;
    }
    .feed-item:last-child { border-bottom: none !important; }
    .feed-item.ferr { color: #C0392B !important; font-weight: 600 !important; }
    .feed-item.fok  { color: #6B7A64 !important; }
    .feed-item.finfo{ color: #5B7FAF !important; }
    .feed-title {
        font-size: 0.7rem !important;
        font-weight: 700 !important;
        text-transform: uppercase !important;
        letter-spacing: 1.5px !important;
        color: #C8A97E !important;
        margin-bottom: 8px !important;
        padding-bottom: 6px !important;
        border-bottom: 1px solid #E5E0D8 !important;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════
def init_session_state():
    defaults = {
        # Scan
        "is_scanning": False,
        "scan_complete": False,
        "logs": [],
        "posts_data": [],
        "total_posts": 0,
        "total_comments": 0,
        "bot_suspects": 0,
        "status_text": "IDLE",
        "progress_current": 0,
        "progress_total": 0,
        "scan_start_time": None,
        "gallery_id_last": "",
        # AI Brain
        "brain_api_key": "",
        "brain_result": None,
        "brain_error": "",
        "suggested_topic": "",
        # Poster
        "post_logs": [],
        # Pipeline (editable fields)
        "edit_title": "",
        "edit_content": "",
        # Bento Metrics
        "ai_posts_count": 0,
        "ai_comments_count": 0,
        # Swarm Mode
        "swarm_running": False,
        "swarm_log": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session_state()


# ══════════════════════════════════════════════
# Async Crawling Bridge
# ══════════════════════════════════════════════
def _safe_state_get(key, default=None):
    try:
        return st.session_state.get(key, default)
    except Exception:
        return default


def _safe_state_set(key, value):
    try:
        st.session_state[key] = value
    except Exception:
        pass


def add_log(msg: str):
    try:
        logs = _safe_state_get("logs", [])
        logs.append(msg)
        if len(logs) > 200:
            logs = logs[-200:]
        _safe_state_set("logs", logs)
    except Exception:
        pass


async def _log_callback(msg: str):
    clean = re.sub(r"\[/?[^\]]*\]", "", msg)
    add_log(clean)


async def _progress_callback(current: int, total: int):
    _safe_state_set("progress_current", current)
    _safe_state_set("progress_total", total)


async def _status_callback(text: str, is_alert: bool):
    _safe_state_set("status_text", text)


async def _run_scrape(gallery_id: str, time_limit_hours: float, headless: bool):
    scraper = GalleryScraper(headless=headless)
    try:
        _safe_state_set("status_text", "INITIALIZING...")
        total = await scraper.run_full_scrape(
            gallery_id=gallery_id,
            time_limit_hours=time_limit_hours,
            log=_log_callback,
            progress=_progress_callback,
            status_cb=_status_callback,
        )
        _safe_state_set("total_posts", scraper.stats_posts_scraped)
        _safe_state_set("total_comments", scraper.stats_comments_scraped)
        _safe_state_set("bot_suspects", scraper.stats_bot_suspects)
        _safe_state_set("status_text", f"COMPLETE - {total} posts saved")
        add_log(f"> SCAN COMPLETE: {total} posts saved")
    except Exception as e:
        _safe_state_set("status_text", f"ERROR: {str(e)[:80]}")
        add_log(f"> CRITICAL ERROR: {str(e)}")
    finally:
        _safe_state_set("is_scanning", False)
        _safe_state_set("scan_complete", True)


def _thread_target(gallery_id: str, time_limit_hours: float, headless: bool):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run_scrape(gallery_id, time_limit_hours, headless))
    finally:
        loop.close()


# ══════════════════════════════════════════════
# Helper: Hot Keyword Extraction
# ══════════════════════════════════════════════
def extract_hot_keywords(posts_data: list, top_n: int = 15) -> list[tuple[str, int]]:
    """게시글 데이터에서 핫 키워드를 추출하여 (단어, 빈도) 리스트 반환."""
    if not posts_data:
        return []
    all_text = " ".join(
        str(p.get("title", "")) + " " + str(p.get("content", ""))
        for p in posts_data
    )
    words = re.findall(r"[가-힣a-zA-Z]{2,}", all_text)
    filtered = [w for w in words if w.lower() not in KEYWORD_STOPWORDS]
    return Counter(filtered).most_common(top_n)


# ══════════════════════════════════════════════
# Helper: Log HTML
# ══════════════════════════════════════════════
def render_log_html(logs: list, max_lines: int = 80, height: int = 300) -> str:
    parts = []
    for line in reversed(logs[-max_lines:]):
        css = "log-line"
        if any(kw in line for kw in ("ERROR", "BLOCK", "FAIL", "ERR")):
            css = "log-error"
        elif any(kw in line for kw in ("OK", "DONE", "COMPLETE", "✅")):
            css = "log-ok"
        elif any(kw in line for kw in ("INFO", "PHASE")):
            css = "log-info"
        elif "[W" in line:
            css = "log-worker"
        parts.append(f'<div class="{css}">{_html.escape(line)}</div>')
    content = "\n".join(parts)
    return f'<div class="log-box" style="height:{height}px;">{content}</div>'


def render_feed_html(logs: list, max_lines: int = 150, height_px: int = 680) -> str:
    """우측 Latest Updates 피드 HTML 렌더링 — 세로형 실시간 로그."""
    parts = []
    for line in reversed(logs[-max_lines:]):
        css = "feed-item"
        if any(kw in line for kw in ("ERROR", "BLOCK", "FAIL", "ERR", "❌", "실패")):
            css = "feed-item ferr"
        elif any(kw in line for kw in ("OK", "DONE", "COMPLETE", "✅", "🎉", "성공", "완료")):
            css = "feed-item fok"
        elif any(kw in line for kw in ("⌨️", "🔑", "📄", "🌐", "WAVE", "🧠", "🎲", "📡")):
            css = "feed-item finfo"
        parts.append(f'<div class="{css}">{_html.escape(line)}</div>')
    body = "\n".join(parts) if parts else (
        '<div class="feed-item" style="color:#ccc;font-style:italic">No events yet.</div>'
    )
    return f'<div class="latest-feed" style="height:{height_px}px;">{body}</div>'


# ══════════════════════════════════════════════
# Sidebar
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        '<div class="sidebar-title">👻 <span>GHOST</span> PROTOCOL</div>',
        unsafe_allow_html=True,
    )
    st.caption("v5.0 · Swarm Bento Pipeline")
    st.divider()

    gallery_id = st.text_input(
        "🎯 Gallery ID",
        value="stockus",
        help="DC Inside 갤러리 ID",
        disabled=st.session_state.is_scanning,
    )

    tone_map = {
        "🧊 냉소적 (Cynical)": "cynical",
        "😐 중립 (Neutral)": "neutral",
        "📊 분석적 (Analytical)": "analytical",
        "🗣️ 독백 (Monologue)": "monologue",
        "🔥 공격적 (Aggressive)": "aggressive",
        "💀 어그로성 (Aggro)": "aggro",
    }
    tone_label = st.selectbox(
        "🎭 Tone", options=list(tone_map.keys()), index=0,
        disabled=st.session_state.is_scanning,
    )
    neural_tone = tone_map[tone_label]

    length_options = ["아주 짧게 (1문장)", "짧게 (1~2문장)", "보통 (3~4문장)"]
    selected_length = st.selectbox(
        "📏 Length", options=length_options, index=2,
        disabled=st.session_state.is_scanning,
    )

    max_scrape_minutes = st.slider(
        "⏱️ Scan Range (Min)", 10, 180, 60, 10,
        help="수집 시간 범위 (분)",
        disabled=st.session_state.is_scanning,
    )
    time_limit = max_scrape_minutes / 60

    headless = st.toggle(
        "🕶️ Headless", value=True,
        help="ON: 브라우저 숨김 / OFF: 디버깅",
        disabled=st.session_state.is_scanning,
    )

    st.divider()

    st.subheader("🔑 API Key")
    api_key = st.text_input(
        "Gemini API Key", type="password",
        value=st.session_state.brain_api_key,
        label_visibility="collapsed",
    )
    st.session_state.brain_api_key = api_key

    _env_key = os.getenv("GEMINI_API_KEY", "")
    has_any_key = bool(st.session_state.brain_api_key or _env_key)
    if _env_key and not st.session_state.brain_api_key:
        st.caption("✅ .env 키 감지됨")

    st.divider()
    if st.button("📤 Export CSV", use_container_width=True):
        gid_exp = st.session_state.gallery_id_last or gallery_id
        database.init_db()
        pc = database.export_posts_csv(gid_exp, f"data/{gid_exp}_posts_export.csv")
        cc = database.export_comments_csv(gid_exp, f"data/{gid_exp}_comments_export.csv")
        if pc or cc:
            st.success(f"{pc} posts, {cc} comments")
        else:
            st.warning("No data")


# ══════════════════════════════════════════════
# Main Area
# ══════════════════════════════════════════════
gid = st.session_state.gallery_id_last or gallery_id

# DB 데이터 로드
if st.session_state.is_scanning or st.session_state.scan_complete:
    try:
        database.init_db()
        st.session_state.total_posts = database.get_post_count(gid)
        st.session_state.total_comments = database.get_comment_count(gid)
        all_posts = database.get_all_posts(gid)
        st.session_state.posts_data = all_posts[:100]
    except Exception:
        pass

# ── Bento Metric Cards ──
# AI 지분율 계산
_ai_share_pct = 0.0
_total_p = st.session_state.total_posts
if _total_p > 0:
    try:
        database.init_db()
        _ai_count = database.get_ai_post_count(gid)
        _ai_share_pct = round((_ai_count / _total_p) * 100, 1)
    except Exception:
        pass

mc1, mc2, mc3, mc4 = st.columns(4)
with mc1:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="mc-icon">🔍</div>'
        f'<div class="mc-label">총 스캔 수</div>'
        f'<div class="mc-value">{st.session_state.total_posts:,}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with mc2:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="mc-icon">🤖</div>'
        f'<div class="mc-label">AI 침투율</div>'
        f'<div class="mc-value">{_ai_share_pct}%</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with mc3:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="mc-icon">🚀</div>'
        f'<div class="mc-label">포스팅 성공</div>'
        f'<div class="mc-value">{st.session_state.ai_posts_count}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with mc4:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="mc-icon">🕵️</div>'
        f'<div class="mc-label">봇 탐지</div>'
        f'<div class="mc-value">{st.session_state.bot_suspects}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

# ── Progress Bar ──
if st.session_state.is_scanning:
    pt = st.session_state.progress_total
    pc = st.session_state.progress_current
    if pt > 0:
        st.progress(pc / pt, text=f"Scanning... {pc}/{pt}")
    else:
        st.progress(0, text="Collecting post list...")

# ══════════════════════════════════════════════
# SLA Dashboard — [3 : 1] Bento Grid
# ══════════════════════════════════════════════
col_main, col_log = st.columns([3, 1])

# ─────────────────────────────────────────────
# MAIN COLUMN (3): STEP 1 → STEP 2 → STEP 3
# ─────────────────────────────────────────────
with col_main:

    # ── STEP 1: SCAN ──
    st.markdown(
        '<div class="bento">'
        '<span class="step-hdr step-hdr-scan">STEP 1 — 🔍 트렌드 스캔</span>',
        unsafe_allow_html=True,
    )

    s1_col1, s1_col2 = st.columns([3, 1])
    with s1_col1:
        scan_clicked = st.button(
            "▶ SCAN START", use_container_width=True,
            disabled=st.session_state.is_scanning, type="primary",
        )
    with s1_col2:
        stop_clicked = st.button(
            "⏹ STOP", use_container_width=True,
            disabled=not st.session_state.is_scanning,
        )

    if scan_clicked:
        st.session_state.is_scanning = True
        st.session_state.scan_complete = False
        st.session_state.logs = []
        st.session_state.posts_data = []
        st.session_state.total_posts = 0
        st.session_state.total_comments = 0
        st.session_state.bot_suspects = 0
        st.session_state.progress_current = 0
        st.session_state.progress_total = 0
        st.session_state.status_text = "STARTING..."
        st.session_state.scan_start_time = time.time()
        st.session_state.gallery_id_last = gallery_id
        t = threading.Thread(
            target=_thread_target,
            args=(gallery_id, time_limit, headless),
            daemon=True,
        )
        add_script_run_ctx(t)
        t.start()
        st.rerun()

    if stop_clicked:
        st.session_state.is_scanning = False
        st.session_state.status_text = "STOPPED BY USER"
        add_log("> USER REQUESTED STOP")
        st.rerun()

    # Status
    status = st.session_state.status_text
    if "ERROR" in status or "BLOCK" in status:
        st.error(f"⚠️ {status}")
    elif "COMPLETE" in status:
        st.success(f"✅ {status}")
    elif st.session_state.is_scanning:
        st.info(f"🔄 {status}")

    # Hot Keywords
    if st.session_state.posts_data and st.session_state.scan_complete:
        wc = extract_hot_keywords(st.session_state.posts_data, top_n=15)
        if wc:
            top_n = wc[0][1]
            tags = ""
            for w, c in wc:
                css = "kw-tag-hot" if c >= top_n * 0.7 else ""
                tags += f'<span class="kw-tag {css}">{w} ({c})</span>'
            st.markdown(f'<div style="padding:6px 0">{tags}</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # ── STEP 2: BRAIN ──
    st.markdown(
        '<div class="bento">'
        '<span class="step-hdr step-hdr-brain">STEP 2 — 🧠 AI 뻘글 생성</span>',
        unsafe_allow_html=True,
    )

    if not has_any_key:
        st.caption("🔑 API Key를 사이드바에 입력하면 활성화됩니다.")
    else:
        topic_col, suggest_col = st.columns([4, 1])
        with topic_col:
            neural_topic = st.text_input(
                "📝 Topic",
                value=st.session_state.suggested_topic,
                placeholder="",
            )
        with suggest_col:
            st.markdown("<br>", unsafe_allow_html=True)
            suggest_clicked = st.button("🎲 추천", use_container_width=True)

        if suggest_clicked:
            add_log("[APP] 🎲 AI 주제 추천 요청 중...")
            try:
                database.init_db()
                wc = extract_hot_keywords(st.session_state.posts_data, top_n=10)
                hot_kw = [w for w, _ in wc]
                with st.spinner("🎲 분석 중..."):
                    brain = GhostBrain(api_key=st.session_state.brain_api_key or None)
                    topic = brain.suggest_topic(
                        gallery_id=gid, keywords=hot_kw if hot_kw else None,
                    )
                st.session_state.suggested_topic = topic
                add_log(f"[APP] ✅ 추천된 주제: {topic}")
                st.rerun()
            except Exception as e:
                add_log(f"[APP] ⚠️ 추천 실패: {str(e)[:80]}")
                st.warning(f"추천 실패: {str(e)[:80]}")

        gen_clicked = st.button(
            "⚡ GENERATE", use_container_width=True,
            type="primary", disabled=not neural_topic,
        )

        if gen_clicked and neural_topic:
            add_log(f"[APP] 🧠 글 생성 시작: '{neural_topic[:30]}'")
            try:
                database.init_db()
                _gen_wc = extract_hot_keywords(st.session_state.posts_data, top_n=10)
                _gen_kw = [w for w, _ in _gen_wc]
                with st.spinner("🧠 Generating..."):
                    brain = GhostBrain(api_key=st.session_state.brain_api_key or None)
                    result = brain.generate_post(
                        topic=neural_topic, gallery_id=gid,
                        tone=neural_tone, context_hours=1,
                        length=selected_length,
                        keywords=_gen_kw if _gen_kw else None,
                    )
                st.session_state.brain_result = result
                st.session_state.brain_error = ""
                st.session_state.edit_title = result.get("title", "")
                st.session_state.edit_content = result.get("content", "")
                st.session_state.suggested_topic = ""
                add_log(f"[APP] ✅ 생성 완료: '{result.get('title', '')[:30]}'")
                st.rerun()
            except Exception as e:
                st.session_state.brain_result = None
                st.session_state.brain_error = str(e)
                add_log(f"[APP] ⚠️ 생성 실패: {str(e)[:80]}")

        if st.session_state.brain_error:
            st.error(f"⚠️ {st.session_state.brain_error}")

        if st.session_state.brain_result:
            st.session_state.edit_title = st.text_input(
                "✏️ 제목", value=st.session_state.edit_title, key="inp_title",
            )
            st.session_state.edit_content = st.text_area(
                "✏️ 본문", value=st.session_state.edit_content,
                height=180, key="inp_content",
            )
            if st.button("🗑️ 내용 지우고 다시 쓰기", use_container_width=True):
                st.session_state.edit_title = ""
                st.session_state.edit_content = ""
                st.session_state.brain_result = None
                st.session_state.brain_error = ""
                st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    # ── STEP 3: POST ──
    st.markdown(
        '<div class="bento">'
        '<span class="step-hdr step-hdr-post">STEP 3 — 🚀 자동 포스팅</span>',
        unsafe_allow_html=True,
    )

    swarm_on = st.checkbox("🔥 Swarm Mode (연속 폭격)", value=False)
    swarm_count = 1
    if swarm_on:
        swarm_count = st.slider("반복 횟수", 1, 5, 2)

    has_content = bool(st.session_state.edit_title and st.session_state.edit_content)

    if not has_content and not swarm_on:
        st.caption("Step 2에서 글을 생성하면 활성화됩니다.")
    elif not swarm_on and has_content:
        # Preview Card
        safe_t = _html.escape(st.session_state.edit_title)
        safe_c = _html.escape(st.session_state.edit_content)
        st.markdown(
            f'<div class="preview-card">'
            f'<div class="preview-label">PREVIEW</div>'
            f'<div class="preview-title">{safe_t}</div>'
            f'<div class="preview-body">{safe_c}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        post_clicked = st.button(
            "🚀 POST TO DC INSIDE",
            use_container_width=True, type="primary",
        )

        post_log_container = st.empty()
        if st.session_state.post_logs:
            log_text = "\n".join(reversed(st.session_state.post_logs[-50:]))
            post_log_container.code(log_text, language="text")

        if post_clicked:
            pt = st.session_state.edit_title
            pc = st.session_state.edit_content
            if not pt or not pc:
                st.error("⚠️ 제목 또는 본문이 비어있습니다.")
            else:
                try:
                    accounts = load_accounts()
                except (FileNotFoundError, ValueError) as e:
                    st.error(f"⚠️ 계정 로드 실패: {str(e)}")
                    accounts = None

                if accounts:
                    st.session_state.post_logs = []

                    def ui_log_callback(msg):
                        st.session_state.post_logs.append(msg)
                        log_text = "\n".join(reversed(st.session_state.post_logs[-50:]))
                        post_log_container.code(log_text, language="text")
                        add_log(msg)

                    poster = GhostPoster(headless=headless, gallery_type="mgallery")
                    loop = asyncio.new_event_loop()
                    try:
                        post_result = loop.run_until_complete(
                            poster.auto_post(
                                gallery_id=gid, title=pt,
                                content=pc, log_callback=ui_log_callback,
                            )
                        )
                    finally:
                        loop.close()

                    if post_result["success"]:
                        st.session_state.ai_posts_count += 1
                        st.success(f"✅ {post_result['message']}")
                        st.rerun()
                    else:
                        st.error(f"⚠️ {post_result['message']}")

    # ── SWARM MODE: 연속 폭격 ──
    elif swarm_on and has_any_key:
        swarm_clicked = st.button(
            f"🔥 SWARM START ({swarm_count}회 연속 폭격)",
            use_container_width=True, type="primary",
        )
        swarm_log_container = st.empty()

        if st.session_state.swarm_log:
            swarm_text = "\n".join(reversed(st.session_state.swarm_log[-80:]))
            swarm_log_container.code(swarm_text, language="text")

        if swarm_clicked:
            try:
                accounts = load_accounts()
            except (FileNotFoundError, ValueError) as e:
                st.error(f"⚠️ 계정 로드 실패: {str(e)}")
                accounts = None

            if accounts:
                st.session_state.swarm_running = True
                st.session_state.swarm_log = []

                def swarm_log(msg):
                    st.session_state.swarm_log.append(msg)
                    txt = "\n".join(reversed(st.session_state.swarm_log[-80:]))
                    swarm_log_container.code(txt, language="text")
                    add_log(msg)

                brain = GhostBrain(api_key=st.session_state.brain_api_key or None)
                database.init_db()

                for wave in range(1, swarm_count + 1):
                    swarm_log(f"═══ WAVE {wave}/{swarm_count} ═══")

                    # 1) 증분 스캔 (최근 10분)
                    swarm_log(f"[SWARM {wave}] 📡 증분 스캔 시작 (최근 10분)...")
                    try:
                        scan_loop = asyncio.new_event_loop()
                        scraper = GalleryScraper(headless=headless)
                        scan_total = scan_loop.run_until_complete(
                            scraper.run_full_scrape(
                                gallery_id=gid,
                                time_limit_hours=10 / 60,
                                log=_log_callback,
                                progress=_progress_callback,
                                status_cb=_status_callback,
                            )
                        )
                        scan_loop.close()
                        swarm_log(f"[SWARM {wave}] ✅ 스캔 완료: {scan_total} new posts")
                    except Exception as e:
                        swarm_log(f"[SWARM {wave}] ⚠️ 스캔 실패: {str(e)[:60]}")

                    try:
                        all_p = database.get_all_posts(gid)
                        st.session_state.posts_data = all_p[:100]
                    except Exception:
                        pass

                    # 2) 핫 키워드 기반 suggest_topic
                    swarm_log(f"[SWARM {wave}] 🎲 토픽 자동 추천 중...")
                    wc_swarm = extract_hot_keywords(st.session_state.posts_data, top_n=10)
                    kw_swarm = [w for w, _ in wc_swarm]
                    try:
                        topic = brain.suggest_topic(
                            gallery_id=gid,
                            keywords=kw_swarm if kw_swarm else None,
                        )
                        swarm_log(f"[SWARM {wave}] 📌 추천 토픽: '{topic}'")
                    except Exception as e:
                        topic = "갤러리 떡밥"
                        swarm_log(f"[SWARM {wave}] ⚠️ 토픽 추천 실패: {str(e)[:60]}")

                    # 3) generate_post
                    swarm_log(f"[SWARM {wave}] 🧠 글 생성 중...")
                    try:
                        result = brain.generate_post(
                            topic=topic, gallery_id=gid,
                            tone=neural_tone, context_hours=1,
                            length=selected_length,
                            keywords=kw_swarm if kw_swarm else None,
                        )
                        gen_title = result.get("title", "무제")
                        gen_content = result.get("content", "")
                        swarm_log(f"[SWARM {wave}] ✅ 생성 완료: '{gen_title[:30]}'")
                    except Exception as e:
                        swarm_log(f"[SWARM {wave}] ⚠️ 생성 실패: {str(e)[:60]}")
                        continue

                    # 4) auto_post
                    swarm_log(f"[SWARM {wave}] 🚀 자동 포스팅 시작...")
                    poster = GhostPoster(headless=headless, gallery_type="mgallery")
                    post_loop = asyncio.new_event_loop()
                    try:
                        post_result = post_loop.run_until_complete(
                            poster.auto_post(
                                gallery_id=gid, title=gen_title,
                                content=gen_content,
                                log_callback=swarm_log,
                            )
                        )
                    finally:
                        post_loop.close()

                    if post_result["success"]:
                        st.session_state.ai_posts_count += 1
                        swarm_log(f"[SWARM {wave}] 🎉 포스팅 성공! ({post_result['message']})")
                    else:
                        swarm_log(f"[SWARM {wave}] ❌ 포스팅 실패: {post_result['message']}")

                    if wave < swarm_count:
                        wait_sec = random.randint(60, 180)
                        swarm_log(f"[SWARM] ☕ {wait_sec}초 대기 중... (다음 WAVE {wave + 1})")
                        time.sleep(wait_sec)

                swarm_log(f"═══ SWARM COMPLETE ({swarm_count}회) ═══")
                st.session_state.swarm_running = False
                st.rerun()

    elif swarm_on and not has_any_key:
        st.caption("🔑 API Key를 사이드바에 입력하면 Swarm Mode가 활성화됩니다.")

    st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────
# RIGHT LOG COLUMN (1): Latest Updates Feed
# ─────────────────────────────────────────────
with col_log:
    st.markdown(
        '<div class="bento" style="position:sticky;top:0;">'
        '<div class="feed-title">📡 Latest Updates</div>',
        unsafe_allow_html=True,
    )

    # scan + post + swarm 로그 통합 (시간순 최신 150개)
    _combined_logs = (
        list(st.session_state.logs)
        + list(st.session_state.post_logs)
        + list(st.session_state.swarm_log)
    )
    _combined_logs = _combined_logs[-150:]

    st.markdown(
        render_feed_html(_combined_logs, height_px=680),
        unsafe_allow_html=True,
    )
    if _combined_logs:
        st.caption(f"{len(_combined_logs)} events · newest first")
    st.markdown('</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════
# 하단: 수집 이력 모니터링 테이블 (Full-width)
# ══════════════════════════════════════════════
st.markdown("---")
st.markdown("### 📊 수집 이력 모니터링")

tab_p, tab_c, tab_chart = st.tabs(["📋 Posts", "💬 Comments", "📈 Chart"])

with tab_p:
    pdata = st.session_state.posts_data
    if pdata:
        df = pd.DataFrame(pdata)
        dcols = [c for c in [
            "post_id", "title", "author", "author_type",
            "views", "recommends", "is_winner", "created_at",
        ] if c in df.columns]
        if dcols:
            st.dataframe(df[dcols], use_container_width=True, height=350)
            st.caption(f"{len(df)} posts")
    else:
        st.info("No posts yet. 스캔을 실행하면 데이터가 표시됩니다.")

with tab_c:
    try:
        database.init_db()
        comments = database.get_all_comments(gid)
        if comments:
            df_c = pd.DataFrame(comments[:200])
            ccols = [c for c in [
                "post_id", "author", "content", "is_reply", "created_at"
            ] if c in df_c.columns]
            if ccols:
                st.dataframe(df_c[ccols], use_container_width=True, height=350)
                st.caption(f"{len(comments)} comments (최대 200개 표시)")
        else:
            st.info("No comments yet.")
    except Exception:
        st.info("No comments yet.")

with tab_chart:
    pdata = st.session_state.posts_data
    if pdata:
        df_t = pd.DataFrame(pdata)
        if "scraped_at" in df_t.columns:
            df_t["scraped_at"] = pd.to_datetime(df_t["scraped_at"], errors="coerce")
            df_t = df_t.dropna(subset=["scraped_at"]).sort_values("scraped_at")
            if not df_t.empty:
                df_t["cumulative"] = range(1, len(df_t) + 1)
                fig = px.area(
                    df_t, x="scraped_at", y="cumulative",
                    labels={"scraped_at": "Time", "cumulative": "Posts"},
                )
                fig.update_traces(
                    line=dict(color="#6B7A64", width=2),
                    fillcolor="rgba(107, 122, 100, 0.08)",
                )
                fig.update_layout(
                    paper_bgcolor="#F9F8F6", plot_bgcolor="#FFFFFF",
                    font=dict(color="#5A5A5A"),
                    xaxis=dict(gridcolor="#E5E0D8"),
                    yaxis=dict(gridcolor="#E5E0D8"),
                    margin=dict(t=10, b=30, l=40, r=20), height=300,
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Awaiting data...")

# ── Auto-refresh ──
if st.session_state.is_scanning:
    time.sleep(2)
    st.rerun()
