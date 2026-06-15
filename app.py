"""Composer Workbench

One-page writing cockpit for analysis, draft generation, review, and publishing.

실행: streamlit run app.py
"""

import asyncio
import copy
import concurrent.futures as _cf
import datetime
import html as _html
import json
import os
import queue
import random
import re
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

import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitAPIException

from ghost_protocol import cycle_memory as _cm
from ghost_protocol import database
from ghost_protocol import prompt_manager as pm
from ghost_protocol.application import ai_post_monitor
from ghost_protocol.application import gemini_throttle
from ghost_protocol.application import operator_settings
from ghost_protocol.application import observability
from ghost_protocol.application import rehearsal as rehearsal_flow
from ghost_protocol.application import stability
from ghost_protocol.application.run_logs import append_text_log
from ghost_protocol.application import worker_contracts
from ghost_protocol.application.timeouts import run_with_timeout
from ghost_protocol.brain import GhostBrain, RateLimitError
from ghost_protocol.domain import batch_refill
from ghost_protocol.domain import draft_guidance
from ghost_protocol.domain import gallery_purpose
from ghost_protocol.domain import gallery_style
from ghost_protocol.domain import board_rhythm
from ghost_protocol.domain import naturalness
from ghost_protocol.domain import comment_targets
from ghost_protocol.domain import conversation_planner
from ghost_protocol.domain import writing_enrichment
from ghost_protocol.domain import lineup as lineup_policy
from ghost_protocol.domain.validators import validate_slot_diversity
from ghost_protocol.poster import GhostPoster, load_accounts
from ghost_protocol.ui import formatters as ui_formatters
from ghost_protocol.ui import gallery_history
from ghost_protocol.ui import intel_cache
from ghost_protocol.ui import intel_view_model
from ghost_protocol.ui import options as ui_options
from ghost_protocol.ui.session_state import (
    apply_batch_message,
    apply_intel_message,
    apply_pending_ai_briefing_topic,
    apply_swarm_message,
    init_session_state,
    queue_pending_ai_briefing_topic,
    reset_monitor_stats,
)
from ghost_protocol.ui.theme import launchpad_css


# ══════════════════════════════════════════════
# 공용 타임아웃 래퍼
# ══════════════════════════════════════════════
def _timed(fn, *args, _timeout: float = 30.0, **kwargs):
    """blocking 함수를 별도 스레드에서 실행, _timeout 초 내 완료 안 되면
    concurrent.futures.TimeoutError를 raise한다. 호출자가 직접 catch 할 것."""
    return run_with_timeout(fn, *args, timeout=_timeout, **kwargs)


def _safe_fragment_rerun() -> None:
    """Use fragment rerun when Streamlit allows it.

    Streamlit only accepts scope="fragment" during an actual fragment rerun.
    Falling back to a full app rerun makes the whole page flash, so callers that
    need continuous polling should prefer @st.fragment(run_every=...).
    """

    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        return


def _unique_comment_texts(values: list | tuple) -> list[str]:
    """Collapse duplicate comment strings while preserving order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _record_ai_comments_from_raw_posts(
    raw_posts: list[dict] | None,
    *,
    gallery_id: str,
    log_callback=None,
) -> int:
    """Store comments from raw crawl rows that match DB-marked AI posts."""

    if not raw_posts or not gallery_id:
        return 0
    try:
        database.init_db()
        ai_nos = database.get_ai_post_nos(gallery_id)
    except Exception:
        return 0
    if not ai_nos:
        return 0

    total_inserted = 0
    watched = 0
    for post in raw_posts:
        post_no = str(post.get("post_no") or "").strip()
        if not post_no or post_no not in ai_nos:
            continue
        comments = _unique_comment_texts(list(post.get("comments") or []))
        if not comments:
            continue
        inserted = ai_post_monitor.record_comment_batch(
            gallery_id=gallery_id,
            post_id=post_no,
            comments=comments,
        )
        total_inserted += inserted
        watched += 1

    if log_callback and watched:
        log_callback(
            f"🧭 AI 작성글 댓글 감시 — {watched}개 글에서 새 댓글 {total_inserted}개 저장"
        )
    return total_inserted


def _watch_ai_post_comments_once(
    *,
    gallery_id: str,
    gallery_type: str,
    post_no: str,
    log_callback=None,
) -> int:
    """Fetch and store comments for one known AI-marked post."""

    if not gallery_id or not post_no:
        return 0
    try:
        database.init_db()
        from ghost_protocol.scraper import TrendScraper

        scraper = TrendScraper()
        snapshot = scraper.fetch_post_snapshot(gallery_id, post_no, gallery_type) or {}
        comments = list(snapshot.get("comments") or [])
        ajax_comments = scraper.fetch_comments_ajax(
            gallery_id,
            post_no,
            gallery_type,
            e_s_n_o=str(snapshot.get("e_s_n_o") or ""),
        )
        comments = _unique_comment_texts(comments + list(ajax_comments or []))
        inserted = ai_post_monitor.record_comment_batch(
            gallery_id=gallery_id,
            post_id=post_no,
            comments=comments,
        )
        if log_callback:
            log_callback(
                f"[WATCH] #{post_no} AI 작성글 댓글 확인 — {len(comments)}개 중 새 {inserted}개"
            )
        return inserted
    except Exception as exc:
        if log_callback:
            log_callback(f"[WATCH] ⚠️ AI 작성글 댓글 확인 실패 #{post_no}: {str(exc)[:80]}")
        return 0


def _watch_recent_ai_post_comments(
    *,
    gallery_id: str,
    gallery_type: str,
    limit: int = 5,
    log_callback=None,
) -> int:
    """Refresh comments for recent AI-marked posts without flooding the board."""

    try:
        database.init_db()
        posts = database.get_ai_posts(gallery_id, limit=limit)
    except Exception:
        posts = []
    inserted = 0
    for post in posts:
        post_no = str(post.get("post_id") or "").strip()
        inserted += _watch_ai_post_comments_once(
            gallery_id=gallery_id,
            gallery_type=gallery_type,
            post_no=post_no,
            log_callback=log_callback,
        )
        time.sleep(0.15)
    return inserted

# ══════════════════════════════════════════════
# Page Config
# ══════════════════════════════════════════════
st.set_page_config(
    page_title="작업대",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ══════════════════════════════════════════════
# Lookup Maps (module-level constants)
# ══════════════════════════════════════════════
_LEN_OPTS = ui_options.LENGTH_OPTIONS
_POLL_INTERVAL_SECONDS = 2.2
_DEFAULT_LOG_RETENTION_LIMIT = 400
_REHEARSAL_LOG_RETENTION_LIMIT = 2500
_INFINITE_LOG_RETENTION_LIMIT = 5000
_DEFAULT_LIVE_LOG_LIMIT = 120
_INFINITE_LIVE_LOG_LIMIT = 600
_DEFAULT_COPY_LOG_LIMIT = 300
_INFINITE_COPY_LOG_LIMIT = 2000
_KNOWN_GALLERY_DISPLAY_NAMES = {
    "baseball_new13": "국내야구 갤러리",
    "baseball": "국내야구 갤러리",
    "tcggame": "TCG 갤러리",
    "war": "전쟁 갤러리",
    "boardgame": "보드게임 갤러리",
    "vaundy0606": "Vaundy 갤러리",
}

# ── SWARM 다중 인격 풀 — prompts/personas.json 에서 로드 ───────────────────
# 매 WAVE마다 랜덤으로 한 가지 페르소나를 선택하여 글투 다양성 확보.
# "key"는 brain.py generate_post()의 tones.json 맵과 1:1 대응.
# UI의 고정 톤 설정을 SWARM 내에서 오버라이드함 — 현지인 군중 시뮬레이션.
_PERSONA_POOL: list[dict] = lineup_policy.PERSONA_POOL


def _current_log_retention_limit(ss: object) -> int:
    """Keep long-running sessions readable without losing infinite-mode history."""

    try:
        if bool(ss.get("swarm_infinite")):  # type: ignore[attr-defined]
            return _INFINITE_LOG_RETENTION_LIMIT
        if bool(ss.get("wave_test_mode")):  # type: ignore[attr-defined]
            return _REHEARSAL_LOG_RETENTION_LIMIT
    except Exception:
        return _DEFAULT_LOG_RETENTION_LIMIT
    return _DEFAULT_LOG_RETENTION_LIMIT


def _current_live_log_limit() -> int:
    return (
        _INFINITE_LIVE_LOG_LIMIT
        if st.session_state.get("swarm_infinite")
        else _DEFAULT_LIVE_LOG_LIMIT
    )


def _current_copy_log_limit() -> int:
    return (
        _INFINITE_COPY_LOG_LIMIT
        if st.session_state.get("swarm_infinite")
        else _DEFAULT_COPY_LOG_LIMIT
    )


def _load_ai_post_comments_for_ops(gallery_id: str, *, limit: int = 120) -> list[dict]:
    """Return monitored comments for stability diagnostics without surfacing DB errors."""

    if not gallery_id:
        return []
    try:
        database.init_db()
        return database.get_ai_post_comments(gallery_id, limit=limit)
    except Exception:
        return []


def _evaluate_ops_stability() -> dict:
    gallery_id = (
        st.session_state.get("target_gallery_id")
        or st.session_state.get("intel_gallery_id")
        or st.session_state.get("run_gallery_id")
        or ""
    )
    return stability.evaluate_stability(
        st.session_state,
        scripts=list(st.session_state.get("review_scripts", []) or []),
        logs=_collect_ops_logs() if "_collect_ops_logs" in globals() else [],
        intel_result=st.session_state.get("intel_result"),
        ai_comments=_load_ai_post_comments_for_ops(str(gallery_id)),
    )


def _stop_infinite_for_stability(
    ss: "st.session_state",  # type: ignore[name-defined]
    report: dict,
    *,
    prefix: str = "[OPS]",
) -> bool:
    """Stop infinite mode when the shared stability policy says the run is unsafe."""

    if not ss.get("swarm_infinite") or not report.get("stop_recommended"):
        return False
    findings = list(report.get("findings") or [])
    reason = "운영 안정성 정책에 따라 무한 실행을 멈췄습니다."
    if findings:
        stop_finding = next((item for item in findings if item.get("stop")), findings[0])
        reason = f"{stop_finding.get('title')}: {stop_finding.get('action')}"
    ss["swarm_infinite"] = False
    ss["_ops_last_stop_reason"] = reason
    cfg = dict(ss.get("_batch_gen_config", {}) or {})
    if cfg:
        cfg["infinite"] = False
        ss["_batch_gen_config"] = cfg
    if ss.get("batch_gen_stop_event"):
        try:
            ss.batch_gen_stop_event.set()
        except Exception:
            pass
    ss.setdefault("swarm_log", []).append(f"{prefix} 🛑 {reason}")
    observability.append_event(
        ss,
        kind="stability_stop",
        title="infinite mode stopped by stability policy",
        detail=reason,
        status="critical" if report.get("status") == "critical" else "warn",
        metrics={
            "bad_cycles": report.get("bad_cycles", 0),
            "publish_failures": report.get("publish_failures", 0),
        },
    )
    return True


def _build_balanced_lineup(
    wave_count: int,
    *,
    sentiment_score: int = 0,
    hour: int = -1,
) -> list[dict]:
    """온도 밸런싱된 Wave 라인업을 빌드한다.

    기본 보장 조건:
    - mutant(conviction_defender / solution_proposer / hopium): 1~2개 고정 (drift 시 2개)
    - HOT(aggressive / aggro / doomer / paranoid): 최대 floor(30%)개, 최소 1개
    - NEUTRAL(neutral / analytical): 최소 ceil(10%)개
    - 나머지 슬롯은 WARM(cynical / monologue / meta_observer 등)으로 채움
    - 동일 key 페르소나 최대 2개 (_sample_capped 적용)
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
    return lineup_policy.build_balanced_lineup(
        wave_count,
        sentiment_score=sentiment_score,
        hour=hour,
    )

def _history_load() -> list[dict]:
    """로컬 갤러리 히스토리를 로드. 파일 없거나 손상 시 빈 리스트 반환."""
    return gallery_history.load_history()


def _history_save(gallery_id: str, type_label: str) -> None:
    """갤러리 ID + 타입을 히스토리에 최신순으로 저장."""
    return gallery_history.save_history(gallery_id, type_label)


st.markdown(launchpad_css(), unsafe_allow_html=True)


# ══════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════
def _init_state() -> None:
    return init_session_state(st.session_state)

_init_state()

for _type_key in ("intel_type_label", "target_type_label"):
    st.session_state[_type_key] = ui_options.normalize_gallery_type_label(
        st.session_state.get(_type_key, ui_options.DEFAULT_GALLERY_TYPE_LABEL)
    )
st.session_state["target_tone_label"] = ui_options.normalize_tone_label(
    st.session_state.get("target_tone_label", ui_options.DEFAULT_TONE_LABEL)
)
st.session_state["ai_disclosure_marker"] = operator_settings.DEFAULT_PUBLIC_AI_MARKER
st.session_state["ai_disclosure_enabled"] = False
st.session_state["publish_interval_minutes"] = operator_settings.normalize_publish_interval_minutes(
    st.session_state.get("publish_interval_minutes", 3)
)
st.session_state["ai_comment_watch_limit"] = operator_settings.normalize_ai_comment_watch_limit(
    st.session_state.get(
        "ai_comment_watch_limit", operator_settings.DEFAULT_AI_COMMENT_WATCH_LIMIT
    )
)
st.session_state["gemini_call_min_interval_sec"] = gemini_throttle.normalize_seconds(
    st.session_state.get(
        "gemini_call_min_interval_sec",
        gemini_throttle.DEFAULT_MIN_INTERVAL_SEC,
    ),
    default=gemini_throttle.DEFAULT_MIN_INTERVAL_SEC,
    upper=gemini_throttle.MAX_INTERVAL_SEC,
)
st.session_state["gemini_call_jitter_sec"] = gemini_throttle.normalize_seconds(
    st.session_state.get(
        "gemini_call_jitter_sec",
        gemini_throttle.DEFAULT_JITTER_SEC,
    ),
    default=gemini_throttle.DEFAULT_JITTER_SEC,
    upper=gemini_throttle.MAX_JITTER_SEC,
)
os.environ["GEMINI_CALL_MIN_INTERVAL_SEC"] = str(
    st.session_state["gemini_call_min_interval_sec"]
)
os.environ["GEMINI_CALL_JITTER_SEC"] = str(
    st.session_state["gemini_call_jitter_sec"]
)

apply_pending_ai_briefing_topic(st.session_state)


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
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_LOG, data=msg))

    def q_preview(title: str, content: str, wave: int, status: str) -> None:
        log_q.put(worker_contracts.worker_message(
            worker_contracts.MSG_PREVIEW,
            title=title,
            content=content,
            wave=wave,
            status=status,
        ))

    def q_stat(success: int = 0, fail: int = 0) -> None:
        log_q.put(worker_contracts.worker_message(
            worker_contracts.MSG_STAT,
            success=success,
            fail=fail,
        ))

    try:
        brain = GhostBrain(api_key=api_key or None)
        database.init_db()
    except Exception as e:
        q_log(f"❌ Brain 초기화 실패: {str(e)[:120]}")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_DONE))
        return

    # ── 계정 큐 초기화: load_accounts()는 이미 shuffle 완료 ─────────────────
    # 큐 방식: 각 Wave마다 순서대로 계정을 소비 → 큐 소진 시 재충전 + 재셔플
    # random.choice() 방식 대비 동일 계정 연속 선택 위험 제거.
    try:
        _account_pool = load_accounts()
    except (FileNotFoundError, ValueError) as _ae:
        q_log(f"❌ 계정 로드 실패 — SWARM 중단: {str(_ae)[:120]}")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_DONE))
        return
    _account_queue: list[dict] = list(_account_pool)

    # ── 댓글 타겟 풀 수집 + 기존 댓글 프리패치 (SWARM 시작 시 1회 스냅샷) ──────
    _enriched_pool: list[dict] = []
    try:
        from ghost_protocol.scraper import TrendScraper as _TS
        _ts = _TS()
        _raw_list = _ts.fetch_post_list(gallery_id, gallery_type, page=1)
        try:
            _known_ai_posts = database.get_ai_post_nos(gallery_id)
        except Exception:
            _known_ai_posts = set()
        _candidates = comment_targets.select_comment_target_rows(
            _raw_list,
            known_ai_posts=_known_ai_posts,
            limit=15,
            ai_limit=3,
            include_ai=True,
        )
        for _c in _candidates:
            _snapshot: dict = {}
            _cmts: list[str] = []
            try:
                _snapshot = _ts.fetch_post_snapshot(gallery_id, _c["post_no"], gallery_type)
                _cmts = _ts.fetch_comments_ajax(
                    gallery_id,
                    _c["post_no"],
                    gallery_type,
                    e_s_n_o=str(_snapshot.get("e_s_n_o") or ""),
                )[:5]
            except Exception:
                pass
            _inline = list(_snapshot.get("comments") or [])
            _merged_cmts: list[str] = []
            for _comment in _inline + _cmts:
                _text = str(_comment or "").strip()
                if _text and _text not in _merged_cmts:
                    _merged_cmts.append(_text)
            _enriched_pool.append({
                "post_no":           _c["post_no"],
                "title":             _snapshot.get("source_title") or _c["title"],
                "content":           _snapshot.get("content") or "",
                "existing_comments": _merged_cmts[:5],
                "is_ai_post":        bool(_c.get("is_ai_post")),
                "simulation_only":   bool(_c.get("comment_simulation_only")),
            })
        q_log(f"[SWARM] 📋 댓글 타겟 풀: {len(_enriched_pool)}개 (사람 글 맥락 프리패치 완료)")
    except Exception as _te:
        q_log(f"[SWARM] ⚠️ 댓글 타겟 수집 실패 (SWARM 계속): {str(_te)[:80]}")

    try:
        _known_ai_posts_for_comments = database.get_ai_post_nos(gallery_id)
    except Exception:
        _known_ai_posts_for_comments = set()

    _global_wave = 0
    _cycle       = 0
    _swarm_composition_profile = writing_enrichment.build_composition_profile(
        {"raw_posts": _enriched_pool},
        recent_posts=_enriched_pool,
    )

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
            # 화면에는 노출하지 않고 Wave마다 다른 현지인 페르소나로 작성.
            _persona   = random.choice(_PERSONA_POOL)
            _wave_tone = _persona["key"]
            q_log(f"[W{wave}] 🎭 부여된 페르소나: {_persona['name']} ({_wave_tone})")

            for attempt in range(3):
                if stop_ev.is_set():
                    break
                try:
                    _wave_targets = (
                        random.sample(_enriched_pool, min(3, len(_enriched_pool)))
                        if _enriched_pool else None
                    )
                    result = brain.generate_post(
                        topic=topic,
                        gallery_id=gallery_id,
                        tone=_wave_tone,
                        context_hours=None,
                        length=length,
                        recent_posts=_wave_targets,
                        composition_profile=_swarm_composition_profile,
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
                    _tc_list = comment_targets.mark_target_comments(
                        result.get("target_comments", []),
                        target_posts=_enriched_pool,
                    )
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

            post_title, post_content = gen_title, gen_content

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
                    poster.auto_post(gallery_id=gallery_id, title=post_title,
                                     content=post_content, account=_wave_account,
                                     log_callback=q_log)
                )
            finally:
                loop.close()
                asyncio.set_event_loop(None)

            if post_result["success"]:
                q_stat(success=1)
                q_log(f"[W{wave}] 🎉 포스팅 성공! ({post_result['message']})")
                q_preview(post_title, post_content, wave, "✅ POSTED")
            else:
                q_stat(fail=1)
                q_log(f"[W{wave}] ❌ 포스팅 실패: {post_result['message']}")
                q_preview(post_title, post_content, wave, "❌ FAILED")

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
                    if comment_targets.should_skip_public_comment(
                        _tc,
                        known_ai_posts=_known_ai_posts_for_comments,
                    ):
                        q_log(
                            f"[W{wave}] [SAFE] #{_post_no} AI 작성글 댓글 후보 — "
                            "시너지 리허설 전용으로 실제 발행 생략"
                        )
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
    log_q.put(worker_contracts.worker_message(worker_contracts.MSG_DONE))


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
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_LOG, data=msg))

    try:
        brain = GhostBrain(api_key=api_key or None)
    except Exception as e:
        _log(f"❌ Gemini 초기화 실패: {str(e)[:100]}")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE))
        return

    _log(f"🔍 [{gallery_id}] 트렌드 수집 시작 (AJAX 모드, {pages} 페이지)")
    try:
        scraper  = TrendScraper()
        raw_data = scraper.collect_trending(
            gallery_id=gallery_id, gallery_type=gallery_type,
            pages=pages,
            source_detail_limit=min(max(int(pages), 1) * 30, 120),
            progress_callback=_log,
        )
        _record_ai_comments_from_raw_posts(
            raw_data.get("raw_posts", []),
            gallery_id=gallery_id,
            log_callback=_log,
        )
        rhythm = raw_data.get("posting_rhythm") or {}
        if rhythm.get("interval_count"):
            _log(
                "⏱️ 게시판 리듬 감지 — "
                f"평균 {board_rhythm.format_seconds(rhythm.get('average_seconds'))} / "
                f"추천 발행 간격 {rhythm.get('recommended_minutes')}분"
            )
    except ImportError as e:
        _log(f"❌ 의존성 오류: {e}")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE))
        return
    except Exception as e:
        _log(f"❌ 수집 실패: {str(e)[:120]}")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE))
        return

    if not raw_data.get("titles"):
        _log("⚠️ 수집된 데이터 없음 — 갤러리 ID / 타입 확인 필요")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE))
        return

    _log("🧠 Gemini 트렌드 분석 중...")
    result = None
    for attempt in range(3):
        try:
            result = brain.analyze_trend(raw_data)
            break
        except RateLimitError as exc:
            if attempt < 2:
                backoff = 60 * (attempt + 1)
                detail = re.sub(r"\s+", " ", str(exc)).strip()[:180]
                _log(
                    "⚠️ Rate Limit (429) — "
                    f"{detail} — 수집 결과는 유지하고 {backoff}초 후 분석만 재시도합니다 "
                    f"({attempt + 1}/3)"
                )
                time.sleep(backoff)
                _log("🧠 Gemini 트렌드 분석 재시도 중...")
                continue
            detail = re.sub(r"\s+", " ", str(exc)).strip()[:220]
            _log(f"❌ Rate Limit (429) — 분석 재시도 한도 초과: {detail}")
        except Exception as e:
            _log(f"❌ 분석 실패: {str(e)[:120]}")
        break

    if result:
        stats = result.setdefault("stats", {})
        result["pages"] = int(pages)
        result["posting_rhythm"] = raw_data.get("posting_rhythm") or {}
        stats["pages"] = int(pages)
        stats["pages_requested"] = int(pages)
        result["ai_post_comments"] = database.get_ai_post_comments(gallery_id, limit=80)
        _log("✅ 분석 완료!")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_RESULT, data=result))

    log_q.put(worker_contracts.worker_message(worker_contracts.MSG_INTEL_DONE))


# ══════════════════════════════════════════════════════════════════════════════
# 배치 생성 워커 — LLM 호출만, 포스팅 없음
# ══════════════════════════════════════════════════════════════════════════════

def _validate_slot_diversity(summary: str) -> str | None:
    """summary의 [A:], [B:], [C:] 슬롯 간 핵심 명사 중복을 검사.

    중복 발견 시 경고 문자열 반환, 정상이면 None.
    """
    return validate_slot_diversity(summary)


_COMMENT_TOKEN_STOPWORDS = {
    "오늘", "요즘", "이거", "그거", "저거", "그냥", "진짜", "솔직히", "근데",
    "아니", "다들", "사람", "사람들", "글들", "댓글", "제목", "갤러리",
    "게시판", "분위기", "정도", "느낌", "생각", "뭐냐", "뭔데", "어떻게",
    "왜케", "왜이렇게", "계속", "자꾸", "맨날", "같음", "아님", "있음",
    "특정", "유저", "인물", "집단", "유명인", "연예인", "관련", "이야기",
}


def _topic_tokens_for_match(text: object) -> set[str]:
    """Extract coarse topic tokens for matching generated drafts to comment targets."""

    raw = str(text or "").lower()
    tokens = re.findall(r"[0-9a-z가-힣]{2,}", raw)
    return {
        token
        for token in tokens
        if token not in _COMMENT_TOKEN_STOPWORDS and not token.isdigit()
    }


def _briefing_source_tokens(topic: object) -> set[str]:
    """Tokens from the actual briefing, excluding appended writing instructions."""

    raw = str(topic or "")
    # The worker appends bracketed instruction blocks after the briefing. Those
    # blocks can mention generic examples like "작품명" and must not authorize
    # off-briefing topics.
    base = re.split(r"\n\[[^\]\n]+\]", raw, maxsplit=1)[0]
    return _topic_tokens_for_match(base)


def _draft_matches_briefing(title: str, content: str, topic: object) -> bool:
    source_tokens = _briefing_source_tokens(topic)
    if not source_tokens:
        return True
    draft_tokens = _topic_tokens_for_match(f"{title} {content}")
    return bool(source_tokens & draft_tokens)


def _draft_matches_source_slot(title: str, content: str, plan: dict) -> bool:
    """Return True when an R-slot draft uses its assigned real source post."""

    source_text = " ".join(
        [
            str(plan.get("source_title") or ""),
            str(plan.get("source_content") or ""),
        ]
    )
    source_tokens = _topic_tokens_for_match(source_text)
    if not source_tokens:
        return False
    draft_tokens = _topic_tokens_for_match(f"{title} {content}")
    return bool(source_tokens & draft_tokens)


def _has_generic_meta_reaction(title: str, content: str) -> bool:
    """Detect drafts that only comment on topic frequency instead of the topic."""

    return naturalness.has_generic_meta_reaction(title, content)


def _has_concrete_hook(title: str, content: str) -> bool:
    """Return True when a draft contains a concrete conversational hook."""

    combined = f"{title} {content}"
    if naturalness.has_concrete_hook(title, content):
        return True
    return len(_topic_tokens_for_match(combined)) >= 2


def _has_placeholder_leak(title: str, content: str) -> bool:
    combined = f"{title} {content}"
    return any(
        marker in combined
        for marker in ("특정 유저", "특정 인물", "특정 집단", "특정 특정")
    )


def _has_newbie_definition_question(title: str, content: str) -> bool:
    """Detect outsider-style definition questions that read like a new arrival."""

    return naturalness.has_newbie_definition_question(title, content)


def _has_forced_topic_switch(title: str, content: str) -> bool:
    """Detect forced topic-switch complaints that make the draft look engineered."""

    return naturalness.has_forced_topic_switch(title, content)


def _structure_failure_reasons(
    title: str,
    content: str,
    *,
    style_profile: dict | None = None,
) -> tuple[str, ...]:
    """Detect safe-but-awkward structures that read like review prompts."""

    return naturalness.structure_failure_reasons(
        title,
        content,
        style_profile=style_profile,
    )


def _draft_angle_key(title: str, content: str) -> str:
    """Group drafts by conversational angle, not just noun overlap."""

    combined = f"{title} {content}"
    angle_patterns = (
        ("전개 지연 불만", ("느리", "질질", "언제 끝", "언제 찾", "몇 화째", "시간만", "답답", "스킵")),
        ("등장 확인", ("나옴", "나온", "등장", "발견", "못 봤", "놓친", "이미")),
        ("조연 재평가", ("중요", "핵심", "별거 아닌", "그렇게 중요한")),
        ("용례 반응", ("용례", "뉘앙스", "거기에 붙", "그 표현", "그 단어", "왜 욕", "뭐하는", "뭐 하는")),
        ("표현 반응", ("표현", "드립", "비유", "말투", "용례")),
        ("루머 거리두기", ("루머", "진짜라고", "믿는", "확산", "폭로", "사생활")),
        ("책임/돈 기준", ("책임", "돈", "남탓", "물린", "본인 잘못", "누가 지")),
        ("반박", ("아니지", "그건", "그렇게까지", "오바", "너무 몰아")),
        ("해결 제안", ("그냥", "스킵", "정리", "먼저", "찾아보")),
        ("기준/수치 질문", ("기준", "수치", "몇", "가격", "만원", "순위", "비율")),
        ("타이밍 의심", ("타이밍", "갑자기", "수상", "우연", "뜬금")),
        ("생활 체감", ("귀찮", "힘들", "시간", "돈", "대기", "피곤")),
        ("가능성 기대", ("될 수도", "가능성", "혹시", "나중에", "반전")),
    )
    for key, patterns in angle_patterns:
        if any(pattern in combined for pattern in patterns):
            return key
    return ""


def _has_summary_pileup(title: str, content: str) -> bool:
    """Catch drafts that stack several briefing nouns like a summary paragraph."""

    combined = f"{title} {content}"
    anchor_patterns = (
        "펜던트", "복덕방", "혐치코", "코찰갑", "야대기", "고음", "리센느",
        "과거회상", "주4일제", "단팥빵", "말차", "백탕",
    )
    anchor_hits = sum(1 for token in anchor_patterns if token in combined)
    return anchor_hits >= 3 and any(
        marker in combined
        for marker in ("전개", "분위기", "스토리", "대체", "답답", "뭐 하는지도")
    )


def _filter_target_comments_for_topic(
    target_comments: list[dict],
    *,
    title: str,
    content: str,
    target_posts: list[dict] | None,
) -> list[dict]:
    """Keep only comments whose target post shares concrete topic tokens."""

    if not target_comments or not target_posts:
        return target_comments[:2] if target_comments else []

    generated_tokens = _topic_tokens_for_match(f"{title} {content}")
    if not generated_tokens:
        return target_comments[:2]

    post_lookup = {str(post.get("post_no", "")).strip(): post for post in target_posts}
    filtered: list[dict] = []
    for item in target_comments:
        post_no = str(item.get("post_no", "")).strip()
        target_post = post_lookup.get(post_no)
        if not target_post:
            continue
        post_text = " ".join(
            [
                str(target_post.get("title", "")),
                str(target_post.get("content", "")),
                " ".join(str(c) for c in target_post.get("existing_comments", [])[:3]),
                str(item.get("comment", "")),
            ]
        )
        if generated_tokens & _topic_tokens_for_match(post_text):
            filtered.append(item)

    return filtered[:2]


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
    style_profile: dict | None = None,
    composition_profile: dict | None = None,
    purpose_slot_enabled: bool = True,
    purpose_only: bool = False,
    is_refill: bool = False,
    rehearsal: bool = False,
    rehearsal_cycle: int = 1,
    rehearsal_cycle_limit: int = 1,
    rehearsal_anchor_posts: list[dict] | tuple[dict, ...] | None = None,
    rehearsal_anchor_topic: str = "",
) -> None:
    """백그라운드 스레드: N개 Wave 분량의 대본(제목+본문)을 일괄 사전 생성.
    포스팅은 하지 않는다. 완료 시 batch_done 메시지로 scripts 리스트를 반환.
    infinite=True 면 wave_count를 최대 10으로 제한하여 한 묶음만 생성.
    """

    # ── 디스크 로그 파일 — UI 상태와 무관하게 항상 보존 ──────────────
    _log_dir = Path(__file__).parent / "logs"
    _log_dir.mkdir(exist_ok=True)
    _runtime_log_path = _log_dir / "batch_runtime.log"
    _runtime_log_file = open(_runtime_log_path, "w", encoding="utf-8")
    _runtime_log_file.write(f"=== Batch Runtime Log · {datetime.datetime.now().isoformat()} ===\n\n")
    _runtime_log_file.flush()

    def q_log(msg: str) -> None:
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_LOG, data=msg))
        # 디스크에도 실시간 기록 — 중단/크래시에도 보존
        try:
            _runtime_log_file.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            _runtime_log_file.flush()
        except Exception:
            pass

    # Phase 10: 무한 모드는 항상 10개 강제 (fire_clicked에서 이미 보정하지만 이중 방어)
    actual_count = 10 if infinite or rehearsal else wave_count

    try:
        brain = GhostBrain(api_key=api_key or None)
        database.init_db()
    except Exception as e:
        q_log(f"❌ Brain 초기화 실패: {str(e)[:120]}")
        try:
            _runtime_log_file.close()
        except Exception:
            pass
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_BATCH_DONE, scripts=[]))
        return

    # ── 사이클 메모리 로드 ────────────────────────────────────────────────────
    # 무한 반복 시 화제 고착화·감성 극단화·어휘 수렴을 방지하는 상태 지속 메모리.
    # cycle_memory.json 파일로 사이클 간 영속 저장.
    _mem_root         = _cm.load()
    _mem              = _cm.get_gallery_memory(_mem_root, gallery_id)
    _mem_cycle        = (
        int(_mem.get("cycle_count", 0) or 0)
        if is_refill
        else _cm.increment_cycle(_mem)
    )
    _banned_topics    = _cm.get_banned_topics(_mem)
    _banned_starts    = _cm.get_banned_starts(_mem)
    _banned_title_kws = _cm.get_banned_title_keywords(_mem)
    _sentiment_score  = _cm.get_sentiment_score(_mem)
    _topic_ages       = _cm.get_topic_ages(_mem)
    if _topic_ages:
        _aged = {k: v for k, v in _topic_ages.items() if v >= 3}
        if _aged:
            _age_str = ", ".join(f"{k}({v}cyc)" for k, v in sorted(_aged.items(), key=lambda x: -x[1]))
            q_log(f"[CYCLE-MEM] ⏳ 장기 화제: {_age_str}")
    _current_hour     = datetime.datetime.now().hour
    _batch_first_words: list[str] = []   # 어휘 엔트로피 추적용 first_word 수집
    _used_titles:       list[str] = []   # 배치 내 중복 화제 방지 — 생성된 제목 누적
    _used_title_keys:   set[str] = set() # 공백/대소문자 차이를 제거한 정확 중복 차단
    _angle_counts:      dict[str, int] = {} # 전개 지연/확인 질문 등 발화 각도 수렴 방지
    _slot_success_counts: dict[str, int] = {} # A/B/C/R/G 쿼터 충족 추적
    _question_skeleton_counts: dict[str, int] = {} # 같은 질문형 골격 반복 방지
    _reaction_skeleton_counts: dict[str, int] = {} # 같은 반응 골격 반복 방지
    _successful_topic_families: list[frozenset[str]] = [] # 슬롯을 가로지르는 소재군 추적
    _persona_occurrence_counts: dict[str, int] = {} # 같은 페르소나도 발화 각도 순환
    _direct_question_count = 0  # 질문형은 배치의 양념이지 기본 문형이 아니다.
    _style_block = gallery_style.prompt_block(style_profile)
    if _style_block and "갤러리별 문체 프로필" not in topic:
        topic = f"{topic}\n\n{_style_block}"
        q_log("[BATCH] 🧬 갤러리별 문체 프로필 적용")
    _composition_block = writing_enrichment.prompt_block(composition_profile)
    if _composition_block and "[Composition Profile]" not in topic:
        topic = f"{topic}\n\n{_composition_block}"
        q_log("[BATCH] composition profile applied")

    def _title_key(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    _TITLE_TOPIC_STOPWORDS = {
        "아니", "근데", "그냥", "솔직히", "진짜", "요즘", "오늘", "다들",
        "나만", "대체", "맨날", "자꾸", "계속", "또", "이거", "저거", "그거",
        "뭔데", "뭐임", "왜", "좀", "같음", "같은데", "아님", "있냐", "있음",
        "하냐", "거임", "건지", "나오냐", "나옴", "나오는", "얘기", "글",
        "갤", "갤러리", "피곤", "지겹", "ㄹㅇ", "ㅋㅋ",
    }

    def _title_topic_tokens(value: object) -> list[str]:
        raw = str(value or "").casefold()
        tokens: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[0-9a-z가-힣]{2,}", raw):
            if token.isdigit():
                continue
            for suffix in ("은", "는", "이", "가", "을", "를", "도", "만", "의", "들"):
                if len(token) > 2 and token.endswith(suffix):
                    token = token[:-len(suffix)]
                    break
            if token in _TITLE_TOPIC_STOPWORDS or len(token) < 2:
                continue
            if token not in seen:
                tokens.append(token)
                seen.add(token)
        return tokens

    # 밈 풀 추출 — topic 문자열에서 "밈: X · Y" 패턴 파싱
    import re as _re
    _meme_pool: list[str] = []
    _meme_match = _re.search(r"밈\s*[:：]\s*(.+?)(?:\n|$)", topic)
    if _meme_match:
        _meme_pool = [m.strip() for m in _meme_match.group(1).split("·") if m.strip()]

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

    # 제목 키워드 반복 금지어 주입 — 이전 배치에서 반복 감지된 제목 소재 차단
    if _banned_title_kws:
        _title_kw_str = " / ".join(_banned_title_kws)
        topic = (
            topic
            + f"\n[⛔ 반복 제목 키워드 금지 (이전 배치에서 과다 반복 감지)]: {_title_kw_str}"
        )
        q_log(f"[CYCLE-MEM] 📰 제목 키워드 금지 {len(_banned_title_kws)}개: {_title_kw_str}")

    _drift_streak = _mem.get("drift_streak", 0)
    if _sentiment_score <= _cm.DRIFT_THRESHOLD:
        q_log(f"[CYCLE-MEM] 🌡️ 감성 drift 감지 (score={_sentiment_score}, 연속={_drift_streak}) — HOT 상한 절반, mutant 최대 적용")
        if _drift_streak >= _cm.DRIFT_RECOVERY_AFTER - 1:
            q_log(f"[CYCLE-MEM] 🔄 DRIFT 연속 {_drift_streak+1}사이클 — 다음 갱신 시 감성 리셋 예정")

    # ── 화제 생명주기 피로 알림 — 장기 화제에 대해 LLM 경고 주입 ────────
    if _topic_ages:
        _stale = [k for k, v in _topic_ages.items() if v >= 5]
        if _stale:
            _stale_str = ", ".join(_stale)
            topic += (
                f"\n[⏳ 장기 화제 피로 경고] 다음 소재는 {5}사이클 이상 반복된 낡은 떡밥입니다: {_stale_str}. "
                "이 소재는 가급적 피하고 신선한 각도나 완전히 새로운 화제를 우선하세요."
            )
            q_log(f"[CYCLE-MEM] ⏳ 장기 화제 피로 경고 주입: {_stale_str}")

    # ── 자기강화 피드백 루프 차단 — 동일 소재의 관점 분산 ───────────────
    # 화제를 강제로 갈아타면 게시판 흐름과 동떨어진 글이 된다. 원본 데이터
    # 안에서 장면·행동·판단·결과를 나눠 같은 말의 복제만 막는다.
    _total_bans = len(_banned_topics) + len(_banned_starts) + len(_banned_title_kws)
    if _total_bans >= 2:
        topic += (
            "\n[🔄 관점 분산] 현재 화제를 억지로 버리지 마세요. 수집된 원본 안에서 "
            "서로 다른 장면·행동·숫자·경험·결과를 골라 글마다 새 정보를 하나씩 더하세요. "
            "같은 명사를 어미만 바꿔 반복하거나 화제가 지겹다는 말로 회피하지 마세요."
        )
        q_log(f"[CYCLE-MEM] 🔄 관점 분산 주입 (금지 항목 {_total_bans}개)")

    # ── 갤러리 이름 기반 파생 각도 확보 ────────────────────────────────────
    # 여론 핫토픽에만 의존하지 않고, 갤러리 ID/이름에서 이어지는
    # 안전한 질문·비교·주변 소재를 섞도록 유도.
    if gallery_id:
        topic += (
            "\n[🎲 참여 각도 확보] 핫토픽 문장을 복제하지 말고, 갤러리 목적 프로필과 "
            "최근 원본 세트에서 실제로 확인되는 구체 장면·숫자·행동·후속 결과를 섞어라. "
            "ID 문자열만 보고 주제를 추측하지 말고 데이터에 없는 사건이나 경험을 만들지 마라. "
            "안전상 직접 다루기 어려운 원문은 반박문·훈계문으로 바꾸지 말고, "
            "입력에 있는 다른 안전한 원본 장면이나 서브 소재로 즉시 이동하라. "
            "'심각하다/지겹다/왜 자꾸/기준이 모호하다/과한 것 같다' 같은 외부인식 총평은 쓰지 마라."
        )
        q_log(f"[CYCLE-MEM] 🎲 파생 각도 지시 주입 (gallery_id={gallery_id})")

    if not is_refill:
        _cm.save(_mem_root)   # cycle_count 증가 즉시 저장

    # ── 발화 렌즈 풀 로드 ──────────────────────────────────────────────────
    # 무한 반복 시 발화 성향이 사이클마다 동일해지는 문제를 방지.
    # 25% 확률로 wave별 관찰 렌즈를 topic에 오버레이.
    _bot_identities: list[dict] = pm.load_json("bot_identities.json") or []

    # ── 세계관 자동 갱신 (무한 모드 전용: 직전 배치 발행 직후 최신 갤러리 반영) ──
    # auto_refresh=True → 1페이지 재스캔 + analyze_trend() 실행.
    # 성공 시: topic 로컬 변수를 새 ai_analysis로 교체 → 이 배치 전체에 적용.
    # 실패 시: 기존 topic 그대로 유지 (silent fallback).
    if auto_refresh and not stop_ev.is_set():
        q_log("[🔄 AUTO-REFRESH] 갤러리 재스캔 + 세계관 갱신 중...")
        try:
            from ghost_protocol.scraper import TrendScraper as _AR_TS
            # 외부 자극 강제 주입: 기본 2페이지, 3사이클마다 3페이지
            # 봇 점유율이 높을수록 사람 글이 적으므로 더 넓게 스캔
            _scrape_pages = 3 if (_mem_cycle % 3 == 0) else 2
            if _scrape_pages > 2:
                q_log(f"[AUTO-REFRESH] 🌐 사이클 {_mem_cycle} — 외부 자극 강화 ({_scrape_pages}페이지 스크래핑)")
            _ar_raw = _AR_TS().collect_trending(
                gallery_id=gallery_id, gallery_type=gallery_type, pages=_scrape_pages,
            )
            # 봇 점유율 경고 — 사람 글이 부족하면 추가 스캔
            _ar_bot_cnt = _ar_raw.get("ai_post_count", 0)
            _ar_total   = _ar_raw.get("total_post_count", 1)
            _ar_bot_pct = _ar_bot_cnt / max(_ar_total, 1)
            if _ar_bot_pct > 0.5:
                q_log(f"[AUTO-REFRESH] ⚠️ 봇 점유율 {_ar_bot_pct:.0%} — 사람 글 부족, 외부 데이터 의존 필요")
            if _ar_raw.get("titles"):
                # ── Gemini 분석 타임아웃 래퍼 ─────────────────────────────────────
                # brain.analyze_trend()는 google.genai SDK를 동기 호출하며,
                # 네트워크 지연 / Rate Limit 무응답 시 무한 대기(Hang)를 유발한다.
                # → ThreadPoolExecutor + result(timeout=25)로 25초 이내로 제한.
                # 타임아웃 초과 시 orphan 스레드가 남지만 워커는 즉시 폴백 진행.
                _ar_result = None
                try:
                    _ar_result = _timed(
                        brain.analyze_trend,
                        _ar_raw,
                        _timeout=25,
                    )
                except _cf.TimeoutError:
                    q_log("[AUTO-REFRESH] ⚠️ AI 분석 타임아웃 (25s) — 기존 토픽 유지")
                except Exception as _ar_inner_e:
                    q_log(f"[AUTO-REFRESH] ⚠️ AI 분석 실패: {str(_ar_inner_e)[:80]}")

                if _ar_result:
                    _fresh_ai      = (_ar_result.get("ai_analysis") or "").strip()
                    _fresh_summary = (_ar_result.get("summary") or "").strip()
                    _fresh_guidance = (_ar_result.get("generation_guidance") or "").strip()
                    _fresh_composition_block = writing_enrichment.prompt_block(
                        _ar_result.get("composition_profile")
                    )
                    if _fresh_composition_block:
                        _fresh_guidance = "\n\n".join(
                            part for part in (_fresh_guidance, _fresh_composition_block) if part
                        )
                    _slot_guidance = ""
                    # ── 슬롯 의미 중복 검사 ─────────────────────────────
                    if _fresh_summary:
                        _slot_overlap = _validate_slot_diversity(_fresh_summary)
                        if _slot_overlap:
                            q_log(f"[QC] ⚠️ 슬롯 명사 중복 감지: {_slot_overlap}")
                            _slot_guidance = (
                                "[슬롯 다양성 보정] 씨앗 떡밥 A/B/C가 비슷한 명사를 공유합니다. "
                                "브리핑의 큰 주제는 유지하되 같은 제목 구조를 반복하지 말고, "
                                "작품명·구체 표현·독자 반응·반박·해결책·비교처럼 서로 다른 관점으로 나누세요."
                            )
                    _guidance_block = "\n".join(
                        part for part in (_fresh_guidance, _slot_guidance) if part
                    ).strip()
                    _fresh_topic   = (
                        _fresh_ai
                        + ("\n씨앗 떡밥: " + _fresh_summary if _fresh_summary else "")
                        + ("\n\n[작문 지시]\n" + _guidance_block if _guidance_block else "")
                    ).strip()
                    if _fresh_topic:
                        topic = _fresh_topic   # 이 배치의 $topic 갱신
                        # 금지 화제·어휘 재주입 (갱신된 topic에도 유지)
                        if _banned_topics:
                            topic += f"\n[⛔ 반복 화제 금지]: {' / '.join(_banned_topics)}"
                        if _banned_starts:
                            topic += f"\n[⛔ 본문 첫 어절 금지]: {' / '.join(_banned_starts)}"
                        log_q.put(worker_contracts.worker_message(
                            worker_contracts.MSG_CONTEXT_UPDATED,
                            topic=topic,
                            intel=_ar_result,
                        ))
                        q_log("[AUTO-REFRESH] ✅ 세계관 갱신 완료 — 최신 브리핑으로 대본 생성")
                    else:
                        q_log("[AUTO-REFRESH] ⚠️ 분석 비어있음 — 기존 토픽 유지")

                    # ── 사이클 메모리 갱신 (hot_topics TTL + sentiment 진자) ──────
                    _cm.update_topic_ttl(_mem, _ar_result.get("hot_topics", []))
                    _new_sentiment = _cm.update_sentiment(_mem, _ar_result.get("sentiment", ""))
                    _new_banned    = _cm.get_banned_topics(_mem)
                    _cm.save(_mem_root)
                    q_log(
                        f"[CYCLE-MEM] 💾 TTL 갱신 완료 | "
                        f"금지 화제={_new_banned} | 감성점수={_new_sentiment}"
                    )
                    # ── 여론 + 메모리 상태를 런타임 로그에 기록 ──────────
                    try:
                        _rl = _runtime_log_file
                        _rl.write(f"\n[여론]\n")
                        _rl.write(f"  감성    : {_ar_result.get('sentiment', '—')}\n")
                        _ar_ht = _ar_result.get("hot_topics", [])
                        if _ar_ht:
                            _rl.write(f"  핫토픽  : {' · '.join(str(h) for h in _ar_ht[:5])}\n")
                        _ar_mm = _ar_result.get("memes", [])
                        if _ar_mm:
                            _rl.write(f"  밈      : {' · '.join(str(m) for m in _ar_mm[:4])}\n")
                        _ar_kw = _ar_result.get("top_keywords", [])
                        if _ar_kw:
                            _rl.write(f"  키워드  : {', '.join(str(k) for k in _ar_kw[:12])}\n")
                        _ar_st = _ar_result.get("stats", {})
                        if _ar_st:
                            _rl.write(f"  스캔    : 제목 {_ar_st.get('titles_count',0)}개 · 댓글 {_ar_st.get('comments_count',0)}개\n")
                        _rl.write(f"\n[사이클 메모리]\n")
                        _rl.write(f"  사이클  : {_mem.get('cycle_count', 0)}\n")
                        _drift_s = _cm.get_sentiment_score(_mem)
                        _drift_a = _cm.is_drift_active(_mem)
                        _rl.write(f"  감성합  : {_drift_s}{' ⚠️ DRIFT' if _drift_a else ''}  (hist={_mem.get('sentiment_hist', [])})\n")
                        if _new_banned:
                            _rl.write(f"  금지화제: {' / '.join(_new_banned)}\n")
                        _bs = _cm.get_banned_starts(_mem)
                        if _bs:
                            _rl.write(f"  금지어휘: {' / '.join(_bs)}\n")
                        _bt = _cm.get_banned_title_keywords(_mem)
                        if _bt:
                            _rl.write(f"  금지제목: {' / '.join(_bt)}\n")
                        _rl.write("\n")
                        _rl.flush()
                    except Exception:
                        pass
            else:
                q_log("[AUTO-REFRESH] ⚠️ 수집 데이터 없음 — 기존 토픽 유지")
        except Exception as _ar_e:
            q_log(f"[AUTO-REFRESH] ⚠️ 갱신 실패, 기존 토픽으로 폴백: {str(_ar_e)[:80]}")

    # ── 댓글 타겟 풀 수집 + 기존 댓글 프리패치 (배치 시작 시 1회) ────────────
    # 사람 글만 최대 15개 수집 → 기존 댓글 AJAX 프리패치 → enriched_pool 구성.
    # 매 Wave마다 이 풀에서 랜덤 서브셋 5개를 뽑아 군중 쏠림 현상 방지.
    # Phase 8: 수집 전 로그 출력 + 30초 타임아웃 래퍼 → 블라인드 행 방지.
    _enriched_pool: list[dict] = []
    q_log("[BATCH] 🔍 게시글 목록 및 댓글 맥락 수집 중... (최대 30초)")
    try:
        def _collect_pool() -> list[dict]:
            from ghost_protocol.scraper import TrendScraper as _TS
            _ts = _TS()
            _raw_list = _ts.fetch_post_list(gallery_id, gallery_type, page=1)
            try:
                _known_ai_posts = database.get_ai_post_nos(gallery_id)
            except Exception:
                _known_ai_posts = set()
            _candidates = comment_targets.select_comment_target_rows(
                _raw_list,
                known_ai_posts=_known_ai_posts,
                limit=15,
                ai_limit=3,
                include_ai=True,
            )
            _pool: list[dict] = []
            for _c in _candidates:
                _snapshot: dict = {}
                _cmts: list[str] = []
                try:
                    _snapshot = _ts.fetch_post_snapshot(gallery_id, _c["post_no"], gallery_type)
                    _cmts = _ts.fetch_comments_ajax(
                        gallery_id,
                        _c["post_no"],
                        gallery_type,
                        e_s_n_o=str(_snapshot.get("e_s_n_o") or ""),
                    )[:5]
                except Exception:
                    pass
                _inline = list(_snapshot.get("comments") or [])
                _merged_cmts: list[str] = []
                for _comment in _inline + _cmts:
                    _text = str(_comment or "").strip()
                    if _text and _text not in _merged_cmts:
                        _merged_cmts.append(_text)
                _pool.append({
                    "post_no":           _c["post_no"],
                    "title":             _snapshot.get("source_title") or _c["title"],
                    "content":           _snapshot.get("content") or "",
                    "existing_comments": _merged_cmts[:5],
                    "is_ai_post":        bool(_c.get("is_ai_post")),
                    "simulation_only":   bool(_c.get("comment_simulation_only")),
                })
            return _pool

        _enriched_pool = _timed(_collect_pool, _timeout=30.0)
        q_log(f"[BATCH] 📋 댓글 타겟 풀: {len(_enriched_pool)}개 (맥락 프리패치 완료)")
    except _cf.TimeoutError:
        q_log("[BATCH] ⚠️ 댓글 타겟 수집 타임아웃 (30s) — 빈 풀로 계속 진행")
    except Exception as _te:
        q_log(f"[BATCH] ⚠️ 댓글 타겟 수집 실패 (계속): {str(_te)[:80]}")

    # ── 온도 밸런싱 라인업 빌드 ─────────────────────────────────────────
    # HOT ≤ 30% / NEUTRAL ≥ 10% / mutant 1~2개 보장 / 연속 HOT 3회 이상 불가.
    # sentiment_score: 감성 drift 보정 (≤-2 → HOT 상한 절반, mutant 최대)
    # hour: 시간대 리듬 기반 WARM pool 가중치 조정
    _conversation_plan: dict = {}
    try:
        _conversation_plan = conversation_planner.build_conversation_plan(
            actual_count,
            topic,
            gallery_id=gallery_id,
            source_posts=_enriched_pool,
            purpose_slot_enabled=purpose_slot_enabled,
        )
        _conversation_block = conversation_planner.batch_prompt_block(_conversation_plan)
        if _conversation_block and "[Conversation Arc]" not in str(topic):
            topic = f"{topic}\n\n{_conversation_block}"
        _arc_quotas = _conversation_plan.get("quotas", {})
        if isinstance(_arc_quotas, dict) and _arc_quotas:
            _arc_log = ", ".join(
                f"{_role}={_count}"
                for _role, _count in _arc_quotas.items()
                if int(_count or 0) > 0
            )
            q_log(f"[BATCH] topic arc planned — {_arc_log}")
    except Exception as _arc_e:
        _conversation_plan = {}
        q_log(f"[BATCH] topic arc fallback — {str(_arc_e)[:80]}")

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
        log_q.put(worker_contracts.worker_message(
            worker_contracts.MSG_BATCH_PROGRESS,
            wave=wave,
            total=actual_count,
        ))

        _persona   = _wave_lineup[wave - 1]
        _wave_tone = _persona["key"]
        _persona_occurrence = _persona_occurrence_counts.get(_wave_tone, 0)
        _persona_occurrence_counts[_wave_tone] = _persona_occurrence + 1
        q_log(f"[BATCH] 🎭 [{wave}] 페르소나: {_persona['name']} ({_wave_tone})")

        # ── 일상 소재 강제 슬롯 (코드 레벨) ───────────────────────────────
        # 배치의 마지막 50% Wave는 갤러리 핫토픽 무관 일상/신규 소재 전용.
        # topic에 강제 지시를 넣어 LLM이 여론 핫토픽에 매몰되는 것을 차단.
        _daily_slot_start = max(2, int(actual_count * 0.5)) + 1  # 예: 10개 중 6~10번째
        _is_daily_slot = (
            not purpose_only
            and wave >= _daily_slot_start
            and _total_bans >= 2
        )

        # ── 발화 렌즈 오버레이 (25% 확률) ─────────────────────────────────
        # 특정 관찰 렌즈를 topic에 추가하여 사이클 간 언어 다양성 보장.
        # trigger_keywords 매칭 우선, 없으면 랜덤 선택.
        if purpose_only:
            _wave_plan = draft_guidance.plan_wave_guidance(
                wave,
                actual_count,
                topic,
                persona_key=_wave_tone,
                persona_occurrence=_persona_occurrence,
                gallery_id=gallery_id,
                source_posts=_enriched_pool,
                purpose_slot_enabled=True,
                slot_override="G",
                source_offset=wave - 1,
            )
        else:
            _wave_plan = draft_guidance.select_diverse_plan(
                wave,
                actual_count,
                topic,
                persona_key=_wave_tone,
                persona_occurrence=_persona_occurrence,
                gallery_id=gallery_id,
                source_posts=_enriched_pool,
                purpose_slot_enabled=purpose_slot_enabled,
                success_counts=_slot_success_counts,
                successful_families=_successful_topic_families,
            )
        _wave_topic = topic
        _base_wave_guidance = _wave_plan["guidance"]
        _wave_topic += "\n" + _base_wave_guidance
        _arc_block = conversation_planner.wave_prompt_block(
            _conversation_plan,
            wave,
            slot=str(_wave_plan.get("slot") or ""),
            used_titles=_used_titles,
        )
        if _arc_block:
            _wave_topic += "\n" + _arc_block
            _arc_assignments = _conversation_plan.get("assignments", []) if isinstance(_conversation_plan, dict) else []
            _arc_assignment = (
                _arc_assignments[(wave - 1) % len(_arc_assignments)]
                if isinstance(_arc_assignments, list) and _arc_assignments
                else {}
            )
            q_log(
                f"[BATCH] arc [{wave}] "
                f"{_arc_assignment.get('role', 'auto')} / "
                f"{_arc_assignment.get('stance_key', 'auto')}"
            )
        _wave_topic += (
            "\n[🫥 내부자 참여 규칙] 글의 목적은 게시판을 평가하거나 바로잡는 것이 아니라 "
            "이미 진행 중인 소재에 한 조각을 보태는 것이다. 불평·불만·책임 추궁·도덕적 반박을 "
            "기본 반응으로 쓰지 마라. 위험한 슬롯이면 표현을 순화해 논박하지 말고, "
            "같은 입력 안의 안전한 장면·사물·숫자·후속 상황으로 소재 자체를 교체하라."
        )
        q_log(
            f"[BATCH] 🎚️ [{wave}] 슬롯 {_wave_plan['slot']} · "
            f"각도 {_wave_plan['angle_key']}"
        )

        if _is_daily_slot:
            _wave_topic += (
                "\n[🧩 인접 소재 슬롯] 현재 핫토픽을 그대로 복제하지 말고 "
                "브리핑의 [B]/[C]에서 A와 붙어 있는 주변 표현·숫자·장면 하나를 독립 글처럼 시작해라. "
                "다만 후반부 배치가 흩어지면 안 되므로 결론은 대표 축의 기준·반박·작은 행동으로 다시 붙인다. "
                f"'{gallery_id}'라는 게시판 ID를 스포츠·게임·정치 같은 주제로 추론하지 마라. "
                "허위 사건·가짜 루머·갤러리 활동 메타 평론(글 수, 리젠 속도, 분위기 관찰 등)은 금지."
            )
            q_log(f"[BATCH] 🧩 [{wave}] 인접 소재 슬롯")

        # ── 대화 흐름 연결 — 이전 글에 반응하는 구조적 스레딩 ─────────────
        # 3번째 Wave 이후 30% 확률로 이전 글을 참조하여 대화 연결.
        # "독백 나열" → "토론 시뮬레이션"으로 자연스러움 향상.
        if wave >= 3 and _used_titles and random.random() < 0.30:
            _ref_title = random.choice(_used_titles[-5:])  # 최근 5개 중 랜덤
            _wave_topic += (
                f"\n[💬 대화 연결] 이 갤러리에 '{_ref_title}'라는 글이 올라와 있다. "
                "이 글의 주장에 동의, 반박, 보충, 또는 비꼬기 중 하나의 태도로 반응해라. "
                "단, 해당 글의 제목을 그대로 인용하지 말고 핵심 논점만 자연스럽게 받아쳐라."
            )
            q_log(f"[BATCH] 💬 [{wave}] 대화 연결: '{_ref_title[:25]}' 참조")

        # ── 배치 내 화제 중복 방지 (첫 토큰 빈도 추적) ─────────────────
        # 이번 배치에서 이미 생성된 제목의 첫 토큰(=주제어)을 집계.
        # 같은 주제어가 3회 이상 나오면 해당 키워드를 명시적으로 금지.
        if _used_titles:
            from collections import Counter as _Ctr
            _first_toks = [t.strip().split()[0] for t in _used_titles
                           if t.strip() and len(t.strip().split()[0]) >= 2]
            _tok_freq   = _Ctr(_first_toks)
            _hot_toks   = [tok for tok, cnt in _tok_freq.items() if cnt >= 2]

            _dup_ban = " / ".join(_used_titles[-6:])
            _wave_topic += (
                f"\n[⛔ 이번 배치 기사용 제목 목록 (동일·유사 소재 절대 금지)]: {_dup_ban}"
            )
            if _hot_toks:
                _wave_topic += (
                    f"\n[⛔⛔ 절대 사용 금지 키워드 (이 단어로 시작하는 제목 생성 불가)]: "
                    f"{', '.join(_hot_toks)}"
                )
            if _question_skeleton_counts:
                _shape_str = " / ".join(
                    naturalness.question_skeleton_label(key)
                    for key, count in sorted(
                        _question_skeleton_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                    if count > 0
                )
                if _shape_str:
                    _wave_topic += (
                        f"\n[⛔ 이번 배치에서 이미 쓴 질문 골격 금지]: {_shape_str}. "
                        "같은 주제를 쓰더라도 제목 구조를 질문 반복으로 열지 말고, "
                        "짧은 관찰·반박·장면·수치·행동 제안 중 하나로 시작해라."
                    )
            if _reaction_skeleton_counts:
                _reaction_shape_str = " / ".join(
                    naturalness.reaction_skeleton_label(key)
                    for key, count in sorted(
                        _reaction_skeleton_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                    if count > 0
                )
                if _reaction_shape_str:
                    _wave_topic += (
                        f"\n[⛔ 이번 배치에서 이미 쓴 반응 골격 금지]: "
                        f"{_reaction_shape_str}. 같은 결론을 다른 명사에 붙이지 말고 "
                        "새 장면·수치·행동·결과를 하나 추가해라."
                    )
        if _bot_identities and random.random() < 0.25:
            _matched_ids = [
                bid for bid in _bot_identities
                if any(kw in topic for kw in bid.get("trigger_keywords", []))
            ]
            _chosen_id = random.choice(_matched_ids if _matched_ids else _bot_identities)
            _wave_topic += (
                f"\n[🎭 이 글의 관찰 렌즈: '{_chosen_id['name']}' "
                f"({ _chosen_id['bias'] }) — {_chosen_id['signature_style']}]"
            )
            q_log(f"[BATCH] 🪪 [{wave}] 발화 렌즈 적용: {_chosen_id['name']}")

        gen_title: str | None = None
        gen_content: str = ""
        _tc_list: list[dict] = []
        _last_candidate_title = ""
        _last_candidate_content = ""
        _last_candidate_comments: list[dict] = []
        _failure_reason = "생성 결과가 검증을 통과하지 못했습니다."
        _failure_stage = "post_generation_validation"
        _failure_detail = ""
        _failure_attempts = 0
        _attempted_slots: list[str] = []
        _attempted_families: list[frozenset[str]] = []

        for attempt in range(3):
            if stop_ev.is_set():
                break
            try:
                _failure_attempts = attempt + 1
                if attempt == 0:
                    _attempt_plan = _wave_plan
                    _attempt_topic = _wave_topic
                else:
                    _protected_slot = str(_wave_plan.get("slot") or "").upper()
                    if _protected_slot in {"G", "R"}:
                        _attempt_plan = draft_guidance.plan_wave_guidance(
                            wave + attempt,
                            actual_count,
                            topic,
                            persona_key=_wave_tone,
                            persona_occurrence=_persona_occurrence + attempt,
                            gallery_id=gallery_id,
                            source_posts=_enriched_pool,
                            purpose_slot_enabled=purpose_slot_enabled,
                            slot_override=_protected_slot,
                            source_offset=attempt,
                        )
                    else:
                        _attempt_plan = draft_guidance.select_diverse_plan(
                            wave + attempt,
                            actual_count,
                            topic,
                            persona_key=_wave_tone,
                            persona_occurrence=_persona_occurrence + attempt,
                            gallery_id=gallery_id,
                            source_posts=_enriched_pool,
                            purpose_slot_enabled=purpose_slot_enabled,
                            success_counts=_slot_success_counts,
                            successful_families=_successful_topic_families,
                            excluded_families=_attempted_families,
                        )
                    _attempt_topic = _wave_topic.replace(
                        _base_wave_guidance,
                        _attempt_plan["guidance"],
                        1,
                    )
                    q_log(
                        f"[BATCH] 🔀 [{wave}] 재시도 소재 전환: "
                        f"{_attempted_slots[-1]} → {_attempt_plan['slot']}"
                    )
                _wave_plan = _attempt_plan
                if _wave_plan["slot"] not in _attempted_slots:
                    _attempted_slots.append(_wave_plan["slot"])
                _attempt_family = frozenset(_wave_plan.get("family_tokens", ()))
                if _attempt_family and not any(
                    draft_guidance.same_topic_family(_attempt_family, existing)
                    for existing in _attempted_families
                ):
                    _attempted_families.append(_attempt_family)

                # 매 Wave마다 타겟 풀에서 랜덤 서브셋 선택 — 군중 쏠림 방지
                _wave_targets = None
                if _enriched_pool:
                    _source_post_no = str(
                        _wave_plan.get("source_post_no") or ""
                    ).strip()
                    _source_matches = [
                        post for post in _enriched_pool
                        if str(post.get("post_no") or "").strip() == _source_post_no
                    ]
                    _remaining_pool = [
                        post for post in _enriched_pool
                        if post not in _source_matches
                    ]
                    _wave_targets = [
                        *_source_matches[:1],
                        *random.sample(
                            _remaining_pool,
                            min(3 - len(_source_matches[:1]), len(_remaining_pool)),
                        ),
                    ]
                # Phase 8: generate_post()에 40초 타임아웃 적용 — 무한 대기 차단
                result = _timed(
                    brain.generate_post,
                    _timeout=40.0,
                    topic=_attempt_topic,
                    gallery_id=gallery_id,
                    tone=_wave_tone,
                    context_hours=None,
                    length=length,
                    recent_posts=_wave_targets,
                    composition_profile=composition_profile,
                )
                if result.get("_parse_error") or not result.get("title") or not result.get("content"):
                    reason = "안전 필터" if result.get("_safety_error") else "파싱/빈 응답"
                    _failure_reason = reason
                    _failure_stage = (
                        "safety_filter" if result.get("_safety_error") else "response_parse"
                    )
                    _last_candidate_title = str(
                        result.get("_rejected_title") or ""
                    ).strip()
                    _last_candidate_content = str(
                        result.get("_rejected_content") or ""
                    ).strip()
                    _last_candidate_comments = list(
                        result.get("_rejected_comments") or []
                    )
                    _failure_detail = ", ".join(
                        str(value).strip()
                        for value in (result.get("_safety_reasons") or [])
                        if str(value).strip()
                    )
                    if not _failure_detail:
                        _failure_detail = str(
                            result.get("_raw_response") or ""
                        ).strip()[:2000]
                    if attempt < 2:
                        q_log(f"[BATCH] ❌ [{wave}] {reason} — 재시도 ({attempt+1}/3)")
                        continue
                    q_log(f"[BATCH] ❌ [{wave}] {reason} 3회 — 건너뜀")
                    break

                # ── 슬롯 바인딩 하드락 ─────────────────────────────────────
                # 슬롯 D는 폐지됨. LLM이 D를 선택하면 재시도.
                _tp_data    = result.get("_thought_process", {})
                _slot_raw   = str(_tp_data.get("slot_used", "")).strip().upper()
                _slot_clean = _slot_raw.replace("[", "").replace("]", "")
                if _slot_clean == "D":
                    if attempt < 2:
                        q_log(
                            f"[BATCH] ⚠️ [{wave}] 폐지된 슬롯[D] 선택 — 재시도 ({attempt+1}/3)"
                        )
                        continue
                    else:
                        q_log(
                            f"[BATCH] 🔄 [{wave}] 슬롯[D] 3회 반복 — 이 Wave 스킵"
                        )
                        gen_title = None
                        gen_content = ""
                        break
                _expected_slot = str(_wave_plan.get("slot") or "").upper()
                _context_fallback_slot = (
                    _slot_clean == "CONTEXT"
                    and _expected_slot in {"A", "B", "C", "R", "G"}
                )
                if (
                    _expected_slot in {"A", "B", "C", "R", "G"}
                    and _slot_clean
                    and _slot_clean != _expected_slot
                    and not _context_fallback_slot
                ):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🎚️ [{wave}] 슬롯 이탈 "
                            f"({_slot_clean}≠{_expected_slot}) — 재시도 ({attempt+1}/3)"
                        )
                        continue
                    q_log(f"[BATCH] 🎚️ [{wave}] 슬롯 이탈 반복 — 이 Wave 스킵")
                    gen_title = None
                    gen_content = ""
                    _failure_reason = (
                        f"지정 슬롯 {_expected_slot} 대신 "
                        f"{_slot_clean or '미상'}을 사용했습니다."
                    )
                    break
                if _context_fallback_slot:
                    q_log(
                        f"[BATCH] 🎚️ [{wave}] 슬롯 {_slot_clean}을 "
                        f"{_expected_slot}의 안전 fallback으로 검증 계속"
                    )

                gen_title   = result["title"]
                gen_content = result["content"]
                _punctuated_title = naturalness.ensure_question_punctuation(
                    gen_title
                )
                if _punctuated_title != gen_title:
                    q_log(
                        f"[BATCH] ✍️ [{wave}] 질문형 제목 문장부호 보정: "
                        f"'{gen_title[:30]}' → '{_punctuated_title[:30]}'"
                    )
                    gen_title = _punctuated_title
                _tc_list    = result.get("target_comments", [])
                _last_candidate_title = str(gen_title or "").strip()
                _last_candidate_content = str(gen_content or "").strip()
                _tc_before = len(_tc_list)
                _tc_list = _filter_target_comments_for_topic(
                    _tc_list,
                    title=gen_title,
                    content=gen_content,
                    target_posts=_wave_targets,
                )
                _tc_list = comment_targets.mark_target_comments(
                    _tc_list,
                    target_posts=_wave_targets,
                )
                if _tc_before and len(_tc_list) < _tc_before:
                    q_log(
                        f"[BATCH] 💬 [{wave}] 댓글 타겟 소재 불일치 "
                        f"{_tc_before - len(_tc_list)}개 제거"
                    )
                _last_candidate_comments = list(_tc_list)

                # ══════════════════════════════════════════════════════════
                # ██  POST-GENERATION HARD VALIDATION PIPELINE  ██
                # ══════════════════════════════════════════════════════════
                # 프롬프트 레벨 금지는 LLM이 무시할 수 있으므로,
                # 생성된 결과를 백엔드에서 강제 검증하여 위반 시 재시도.
                # 모든 체크는 attempt < 2이면 continue(재시도).
                # 안전/금지/정확한 중복은 끝까지 막고, 말투/메타성 같은 품질 신호는
                # 마지막 후보를 살려서 커뮤니티식 발화를 지나치게 죽이지 않는다.

                _should_retry = False  # 통합 재시도 플래그
                _should_skip_wave = False  # 금지화제/금지어휘 3회 위반 시 Wave 스킵

                # ── 0) 브리핑 이탈 하드체크 ─────────────────────────────
                # recent_posts_context는 댓글 후보일 뿐이다. 제목/본문이 실제
                # 브리핑·씨앗 떡밥과 전혀 맞지 않으면 최근 댓글 잡음으로 샌 것.
                _matches_purpose_slot = (
                    _wave_plan.get("slot") == "G"
                    and gallery_purpose.text_matches(
                        gallery_id,
                        gen_title,
                        gen_content,
                    )
                )
                _matches_source_slot = (
                    _wave_plan.get("slot") == "R"
                    and _draft_matches_source_slot(
                        gen_title,
                        gen_content,
                        _wave_plan,
                    )
                )
                if _wave_plan.get("slot") == "G" and not _matches_purpose_slot:
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🛰️ [{wave}] 갤러리 본래 주제 누락 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(
                            f"[BATCH] 🛰️ [{wave}] 본래 주제 누락 반복 — 이 Wave 스킵"
                        )
                        _failure_reason = "갤러리 본래 주제 슬롯을 충족하지 못했습니다."
                        _should_skip_wave = True

                if _wave_plan.get("slot") == "R" and not _matches_source_slot:
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🗂️ [{wave}] 실제 최근 글 소재 누락 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(
                            f"[BATCH] 🗂️ [{wave}] 최근 글 소재 누락 반복 — 이 Wave 스킵"
                        )
                        _failure_reason = "실제 최근 글의 지정 소재를 반영하지 못했습니다."
                        _should_skip_wave = True

                if (
                    not _draft_matches_briefing(gen_title, gen_content, topic)
                    and not _matches_purpose_slot
                    and not _matches_source_slot
                ):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🧭 [{wave}] 브리핑 밖 소재 감지 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(f"[BATCH] 🧭 [{wave}] 브리핑 밖 소재 3회 — 이 Wave 스킵")
                        _failure_reason = "브리핑 또는 갤러리 본래 주제와 맞지 않습니다."
                        _should_skip_wave = True

                if not _should_retry and not _should_skip_wave and _has_placeholder_leak(gen_title, gen_content):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🧽 [{wave}] 치환용 문구 노출 감지 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(f"[BATCH] 🧽 [{wave}] 치환용 문구 반복 — 이 Wave 스킵")
                        _should_skip_wave = True

                if not _should_retry and not _should_skip_wave and _has_newbie_definition_question(gen_title, gen_content):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🧭 [{wave}] 뉴비식 뜻 질문 감지 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(f"[BATCH] 🧭 [{wave}] 뜻 질문 반복 — 내부자 용례 반응이 아니라 스킵")
                        _should_skip_wave = True

                if not _should_retry and not _should_skip_wave and _has_forced_topic_switch(gen_title, gen_content):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🧭 [{wave}] 강제 화제전환 말투 감지 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(f"[BATCH] 🧭 [{wave}] 화제전환 말투 반복 — 이 Wave 스킵")
                        _should_skip_wave = True

                if not _should_retry and not _should_skip_wave:
                    _structure_reasons = _structure_failure_reasons(
                        gen_title,
                        gen_content,
                        style_profile=style_profile,
                    )
                    if _structure_reasons:
                        _reason_text = ", ".join(_structure_reasons)
                        if attempt < 2:
                            q_log(
                                f"[BATCH] 🧱 [{wave}] 게시판 말투 구조 위반: {_reason_text} — "
                                f"재시도 ({attempt+1}/3)"
                            )
                            _should_retry = True
                        else:
                            q_log(
                                f"[BATCH] 🧱 [{wave}] 구조 위반 반복: {_reason_text} — "
                                "이 Wave 스킵"
                            )
                            _failure_reason = f"게시판 말투 구조 위반: {_reason_text}"
                            _should_skip_wave = True

                if not _should_retry and not _should_skip_wave and _has_generic_meta_reaction(gen_title, gen_content):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🚫 [{wave}] 빈도 관찰형 메타 반응 감지 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(
                            f"[BATCH] 🚫 [{wave}] 빈도 관찰형 메타 반응 반복 — "
                            "이 Wave 스킵"
                        )
                        _failure_reason = "게시판 빈도만 말하는 메타 반응입니다."
                        _should_skip_wave = True

                if not _should_retry and not _should_skip_wave and _has_summary_pileup(gen_title, gen_content):
                    if attempt < 2:
                        q_log(
                            f"[BATCH] 🧱 [{wave}] 요약형 소재 과적 감지 — "
                            f"재시도 ({attempt+1}/3)"
                        )
                        _should_retry = True
                    else:
                        q_log(
                            f"[BATCH] 🧱 [{wave}] 요약형 소재 과적 반복 — "
                            "이 Wave 스킵"
                        )
                        _failure_reason = "한 글에 소재를 너무 많이 쌓았습니다."
                        _should_skip_wave = True

                if not _should_retry and not _should_skip_wave:
                    _is_direct_question = naturalness.is_direct_question(
                        gen_title,
                        gen_content,
                    )
                    _direct_question_cap = naturalness.direct_question_cap(actual_count)
                    if _is_direct_question and _direct_question_count >= _direct_question_cap:
                        if attempt < 2:
                            q_log(
                                f"[BATCH] ❓ [{wave}] 질문형 비율 상한 "
                                f"({_direct_question_count}/{_direct_question_cap}) — "
                                f"평서형으로 재시도 ({attempt+1}/3)"
                            )
                            _should_retry = True
                        else:
                            q_log(
                                f"[BATCH] ❓ [{wave}] 질문형 과다 반복 — 이 Wave 스킵"
                            )
                            _failure_reason = "배치의 질문형 제목 비율이 너무 높습니다."
                            _should_skip_wave = True

                if not _should_retry and not _should_skip_wave:
                    _question_sig = naturalness.question_skeleton_signature(gen_title, gen_content)
                    if _question_sig:
                        _question_cap = 2 if actual_count >= 16 else 1
                        _question_seen = _question_skeleton_counts.get(_question_sig, 0)
                        if _question_seen >= _question_cap:
                            _question_label = naturalness.question_skeleton_label(_question_sig)
                            if attempt < 2:
                                q_log(
                                    f"[BATCH] 🧩 [{wave}] 질문 골격 반복 감지 "
                                    f"({_question_label} {_question_seen + 1}회) — "
                                    f"재시도 ({attempt+1}/3)"
                                )
                                _should_retry = True
                            elif _question_sig in {"frequency_complaint", "definition_probe"}:
                                q_log(
                                    f"[BATCH] 🧩 [{wave}] 질문 골격 반복: {_question_label} — "
                                    "낮은 관찰 반응이 아니라 스킵"
                                )
                                _should_skip_wave = True
                            else:
                                q_log(
                                    f"[BATCH] 🧩 [{wave}] 질문 골격 반복 경고: {_question_label} — "
                                    "이 Wave 스킵"
                                )
                                _failure_reason = f"질문 골격 반복: {_question_label}"
                                _should_skip_wave = True

                if not _should_retry and not _should_skip_wave:
                    _reaction_sig = naturalness.reaction_skeleton_signature(
                        gen_title,
                        gen_content,
                    )
                    if _reaction_sig:
                        _reaction_cap = 2 if actual_count >= 16 else 1
                        _reaction_seen = _reaction_skeleton_counts.get(
                            _reaction_sig,
                            0,
                        )
                        if _reaction_seen >= _reaction_cap:
                            _reaction_label = naturalness.reaction_skeleton_label(
                                _reaction_sig
                            )
                            if attempt < 2:
                                q_log(
                                    f"[BATCH] 🧱 [{wave}] 반응 골격 반복 감지 "
                                    f"({_reaction_label} {_reaction_seen + 1}회) — "
                                    f"재시도 ({attempt+1}/3)"
                                )
                                _should_retry = True
                            else:
                                q_log(
                                    f"[BATCH] 🧱 [{wave}] 반응 골격 반복: "
                                    f"{_reaction_label} — 이 Wave 스킵"
                                )
                                _failure_reason = f"반응 골격 반복: {_reaction_label}"
                                _should_skip_wave = True

                if not _should_retry and not _should_skip_wave:
                    _candidate_family = draft_guidance.topic_family_tokens(
                        " ".join(
                            [
                                str(_wave_plan.get("slot_text") or ""),
                                gen_title,
                                gen_content,
                            ]
                        )
                    )
                    _family_usage = draft_guidance.topic_family_usage(
                        _candidate_family,
                        _successful_topic_families,
                    )
                    _family_cap = draft_guidance.topic_family_cap(actual_count)
                    if _candidate_family and _family_usage >= _family_cap:
                        if attempt < 2:
                            q_log(
                                f"[BATCH] 🧭 [{wave}] 소재군 상한 "
                                f"({_family_usage + 1}/{_family_cap}) — "
                                f"다른 소재로 재시도 ({attempt+1}/3)"
                            )
                            _should_retry = True
                        else:
                            q_log(
                                f"[BATCH] 🧭 [{wave}] 같은 소재군 반복 — 이 Wave 스킵"
                            )
                            _failure_reason = "같은 소재군이 배치 상한을 초과했습니다."
                            _should_skip_wave = True

                # ── 1) 금지어휘 백엔드 하드체크 ──────────────────────────
                # cycle_memory의 banned_starts/banned_title_kws가 제목에
                # 포함되어 있으면 강제 거부. 프롬프트가 아닌 코드로 차단.
                # 2자 미만 단어는 false positive 방지를 위해 제외.
                _title_lower = gen_title.strip()
                _all_banned_words = {w for w in (set(_banned_starts) | set(_banned_title_kws)) if len(w) >= 2}
                if _all_banned_words:
                    _hit_bw = [bw for bw in _all_banned_words if bw in _title_lower]
                    if _hit_bw:
                        if attempt < 2:
                            q_log(f"[BATCH] ⛔ [{wave}] 금지어휘 하드체크 위반: {_hit_bw} — 재시도 ({attempt+1}/3)")
                            _should_retry = True
                        else:
                            q_log(f"[BATCH] ⛔ [{wave}] 금지어휘 3회 연속 위반 — 이 Wave 스킵")
                            _should_skip_wave = True

                # ── 2) 금지화제 백엔드 하드체크 ──────────────────────────
                # banned_topics의 핵심 키워드가 제목에 포함되면 강제 거부.
                # "사랑아 시끄럽다" → "사랑아"+"시끄럽다" 각각 체크.
                if not _should_retry and not _should_skip_wave and _banned_topics:
                    for _bt in _banned_topics:
                        _bt_words = [w for w in _bt.split() if len(w) >= 2]
                        # 금지화제의 핵심 단어 중 2개 이상이 제목에 있으면 매칭
                        _bt_hits = sum(1 for w in _bt_words if w in _title_lower)
                        if _bt_hits >= min(2, len(_bt_words)):
                            if attempt < 2:
                                q_log(f"[BATCH] ⛔ [{wave}] 금지화제 하드체크 위반: '{_bt}' — 재시도 ({attempt+1}/3)")
                                _should_retry = True
                            else:
                                q_log(f"[BATCH] ⛔ [{wave}] 금지화제 3회 연속 위반 — 이 Wave 스킵")
                                _should_skip_wave = True
                            break

                # ── 3) 동일 대사 복제 방지 ───────────────────────────────
                if not _should_retry and _title_key(gen_title) in _used_title_keys:
                    if attempt < 2:
                        q_log(f"[BATCH] ♻️ [{wave}] 동일 제목 복제 감지 — 재시도 ({attempt+1}/3)")
                        _should_retry = True
                    else:
                        q_log(f"[BATCH] ♻️ [{wave}] 동일 제목 3회 반복 — 이 Wave 스킵")
                        _should_skip_wave = True

                # ── 4) 화제 수렴 하드 체크 ───────────────────────────────
                # 첫 토큰(주제어)이 배치 내 2회 이상 등장하면 재시도 (3→2 강화).
                # 추가: 첫 2토큰이 동일한 경우도 체크 (예: "오토사냥 프로그램")
                if not _should_retry:
                    _gen_toks_raw = gen_title.strip().split()
                    _gen_first = _gen_toks_raw[0] if _gen_toks_raw else ""
                    _gen_first2 = " ".join(_gen_toks_raw[:2]) if len(_gen_toks_raw) >= 2 else ""
                    if _gen_first and len(_gen_first) >= 2:
                        # 첫 2토큰 동일 체크 (더 엄격)
                        _ft2_count = 0
                        if _gen_first2:
                            _ft2_count = sum(
                                1 for t in _used_titles
                                if t.strip() and " ".join(t.strip().split()[:2]) == _gen_first2
                            )
                        # 첫 1토큰 동일 체크
                        _ft_count = sum(
                            1 for t in _used_titles
                            if t.strip() and t.strip().split()[0] == _gen_first
                        )
                        # 첫 2토큰 2회+ 또는 첫 1토큰 3회+ 시 재시도
                        if _ft2_count >= 2 or _ft_count >= 3:
                            _label = _gen_first2 if _ft2_count >= 2 else _gen_first
                            _cnt = _ft2_count if _ft2_count >= 2 else _ft_count
                            if attempt < 2:
                                q_log(
                                    f"[BATCH] 🔁 [{wave}] 화제 수렴 차단: "
                                    f"'{_label}' {_cnt+1}회째 — 재시도 ({attempt+1}/3)"
                                )
                                _should_retry = True
                            else:
                                q_log(f"[BATCH] 🔁 [{wave}] 화제 수렴 반복 — 이 Wave 스킵")
                                _failure_reason = f"같은 제목 시작어가 반복됐습니다: {_label}"
                                _should_skip_wave = True

                # ── 4.5) 의미 핵심어 반복 체크 ───────────────────────────
                # 첫 단어만 바꿔 같은 소재를 반복하는 초안을 막는다.
                if not _should_retry and not _should_skip_wave and _used_titles:
                    _gen_topic_toks = _title_topic_tokens(gen_title)
                    _is_semantic_dup = False
                    _semantic_reason = ""
                    _semantic_prev_title = ""
                    for _prev_title in _used_titles:
                        _prev_topic_toks = _title_topic_tokens(_prev_title)
                        if not _gen_topic_toks or not _prev_topic_toks:
                            continue
                        _shared = set(_gen_topic_toks) & set(_prev_topic_toks)
                        _min_len = max(1, min(len(_gen_topic_toks), len(_prev_topic_toks)))
                        if len(_shared) >= 2 and (len(_shared) / _min_len) >= 0.67:
                            _is_semantic_dup = True
                            _semantic_reason = "핵심어 겹침"
                            _semantic_prev_title = _prev_title
                            break
                    if not _is_semantic_dup and _gen_topic_toks:
                        _core_token = _gen_topic_toks[0]
                        _core_count = sum(
                            1 for _prev_title in _used_titles
                            if _core_token in _title_topic_tokens(_prev_title)
                        )
                        _core_cap = max(3, min(5, actual_count // 3 if actual_count >= 10 else 2))
                        if _core_count >= _core_cap:
                            _is_semantic_dup = True
                            _semantic_reason = f"'{_core_token}' 반복 {_core_count + 1}회"
                            _semantic_prev_title = next(
                                (
                                    _prev_title for _prev_title in _used_titles
                                    if _core_token in _title_topic_tokens(_prev_title)
                                ),
                                "",
                            )
                    if _is_semantic_dup:
                        if attempt < 2:
                            q_log(
                                f"[BATCH] 🔄 [{wave}] 의미 중복 감지 ({_semantic_reason}) — "
                                f"재시도 ({attempt+1}/3)"
                            )
                            _should_retry = True
                        else:
                            q_log(
                                f"[BATCH] 🔄 [{wave}] 의미 중복 반복 "
                                f"({_semantic_reason}) — 이 Wave 스킵"
                            )
                            _failure_reason = f"배치 내 의미 중복: {_semantic_reason}"
                            _should_skip_wave = True

                # ── 5) 메타 표현 백엔드 하드 체크 ─────────────────────────
                # 프롬프트 금지에도 불구하고 생성된 메타 표현을 백엔드에서 강제 거부.
                if not _should_retry:
                    if naturalness.has_hard_meta_reaction(gen_title, gen_content):
                        if attempt < 2:
                            q_log(f"[BATCH] 🚫 [{wave}] 메타 표현 감지 — 재시도 ({attempt+1}/3)")
                            _should_retry = True
                        else:
                            q_log(
                                f"[BATCH] 🚫 [{wave}] 메타 표현 반복 — "
                                "이 Wave 스킵"
                            )
                            _failure_reason = "게시판 활동 자체를 평론하는 메타 표현입니다."
                            _should_skip_wave = True

                # ── 5.5) 발화 각도 수렴 체크 ─────────────────────────────
                # 명사는 달라도 "전개 느림/언제 찾냐/언제 끝남"처럼 같은
                # 반응 각도만 반복되면 실제 게시판보다 생성 티가 난다.
                if not _should_retry and not _should_skip_wave:
                    _angle_key = _draft_angle_key(gen_title, gen_content)
                    if _angle_key:
                        _angle_cap = 2 if actual_count >= 8 else 1
                        _angle_seen = _angle_counts.get(_angle_key, 0)
                        if _angle_seen >= _angle_cap:
                            if attempt < 2:
                                q_log(
                                    f"[BATCH] 🎚️ [{wave}] 발화 각도 수렴 감지 "
                                    f"({_angle_key} {_angle_seen + 1}회) — 재시도 ({attempt+1}/3)"
                                )
                                _should_retry = True
                            else:
                                q_log(f"[BATCH] 🎚️ [{wave}] 발화 각도 수렴 반복 — 이 Wave 스킵")
                                _failure_reason = f"발화 각도 반복: {_angle_key}"
                                _should_skip_wave = True

                # ── 6) 긴 밈 복붙 차단 ──────────────────────────────────
                # 짧은 밈은 커뮤니티 말맛의 핵심이라 허용한다. 다만 긴 문구를
                # 제목에 그대로 복붙하면 원문 재현처럼 보이므로 그때만 재시도.
                if not _should_retry and _meme_pool:
                    for _meme in _meme_pool:
                        _meme_clean = _meme.strip()
                        _is_laugh_only = set(_meme_clean) <= {"ㅋ", "ㅎ"}
                        if (
                            _meme_clean
                            and len(_meme_clean) >= 12
                            and not _is_laugh_only
                            and _meme_clean in gen_title
                        ):
                            if attempt < 2:
                                q_log(f"[BATCH] 🎭 [{wave}] 밈 직접인용 차단: '{_meme_clean}' — 재시도 ({attempt+1}/3)")
                                _should_retry = True
                            else:
                                q_log(f"[BATCH] 🎭 [{wave}] 밈 직접인용 반복 — 이 Wave 스킵")
                                _failure_reason = "긴 밈 문구를 그대로 복제했습니다."
                                _should_skip_wave = True
                            break

                # ── 7) 유사 제목 dedup (토큰 80% 일치 차단) ──────────────
                if not _should_retry:
                    _gen_toks = gen_title.strip().split()
                    _is_near_dup = False
                    if _gen_toks and _used_titles:
                        for _prev in _used_titles:
                            _prev_toks = _prev.strip().split()
                            if not _prev_toks:
                                continue
                            _max_len = max(len(_gen_toks), len(_prev_toks))
                            if _max_len == 0:
                                continue
                            _match = sum(1 for a, b in zip(_gen_toks, _prev_toks) if a == b)
                            _sim = _match / _max_len
                            if _sim >= 0.8:
                                _is_near_dup = True
                                break
                    if _is_near_dup:
                        if attempt < 2:
                            q_log(
                                f"[BATCH] 🔄 [{wave}] 유사 제목 감지 "
                                f"(유사도 {_sim:.0%}) — 재시도 ({attempt+1}/3)"
                            )
                            _should_retry = True
                        else:
                            q_log(f"[BATCH] 🔄 [{wave}] 유사 제목 반복 — 이 Wave 스킵")
                            _failure_reason = "기존 원고와 제목 구조가 너무 유사합니다."
                            _should_skip_wave = True

                # ── 8) 화살표 패턴 과다 사용 차단 ──────────────────────────
                # 배치 내 화살표(<-, <<, ←) 제목이 20%를 초과하면 재시도.
                if not _should_retry and _used_titles:
                    _arrow_pats = ("<-", "<<", "←", ">>")
                    _has_arrow = any(ap in gen_title for ap in _arrow_pats)
                    if _has_arrow:
                        _arrow_cnt = sum(
                            1 for t in _used_titles
                            if any(ap in t for ap in _arrow_pats)
                        )
                        _arrow_ratio = _arrow_cnt / len(_used_titles)
                        if _arrow_ratio >= 0.2:  # 이미 20%+ 화살표 → 추가 불허
                            if attempt < 2:
                                q_log(f"[BATCH] ➡️ [{wave}] 화살표 패턴 과다 ({_arrow_ratio:.0%}) — 재시도 ({attempt+1}/3)")
                                _should_retry = True
                            else:
                                q_log(f"[BATCH] ➡️ [{wave}] 화살표 반복 — 이 Wave 스킵")
                                _failure_reason = "같은 제목 기호 패턴이 반복됐습니다."
                                _should_skip_wave = True

                # ── 9) 제목 잘림 감지 ──────────────────────────────────
                if not _should_retry:
                    _title_len = len(gen_title.strip())
                    if _title_len > 40:
                        _valid_endings = ("?", "!", "ㅋ", "ㅎ", "음", "임", "냐", "네", "다", "함", "됨", "지", "듯", "걸", "데", "겠", "아", "야", "씀", "봄", "셈", "요", "죠", "노", "각", "중")
                        if not gen_title.strip().endswith(_valid_endings):
                            if attempt < 2:
                                q_log(f"[BATCH] ✂️ [{wave}] 제목 잘림 감지 ({_title_len}자) — 재시도 ({attempt+1}/3)")
                                _should_retry = True
                            else:
                                q_log(f"[BATCH] ✂️ [{wave}] 제목 잘림 3회 반복 — 이 Wave 스킵")
                                _should_skip_wave = True

                # ── 통합 재시도 판정 ─────────────────────────────────────
                if _should_skip_wave:
                    q_log(f"[BATCH] ⛔ [{wave}] 금지 위반 스킵 — 대본 생성 중단")
                    _failure_reason = "검증 규칙을 반복해서 통과하지 못했습니다."
                    gen_title = None
                    gen_content = ""
                    break
                if _should_retry and attempt < 2:
                    continue

                # ── LLM Judge — 정규식 통과분만 의미적 품질 판정 ──────────
                # Flash 모델, ~200토큰, 금지화제 변형/메타 표현/배치 중복을 잡음.
                # 정규식 9단계 + Judge 2단계 = 총 11단계 검증.
                _judge_passed = True
                if True:
                    try:
                        _verdict = brain.judge_post(
                            gen_title, gen_content,
                            banned_topics=_banned_topics,
                            batch_titles=_used_titles,
                            gallery_id=gallery_id,
                            topic=_attempt_topic,
                        )
                        if not _verdict.get("pass", True):
                            _judge_passed = False
                            _judge_reason = str(_verdict.get("reason", "사유 없음"))
                            _safety_judge_hit = any(
                                token in _judge_reason
                                for token in (
                                    "금지", "금지어", "금지화제",
                                    "외부", "무관", "보호집단",
                                    "성희롱", "비하", "사칭", "안전",
                                )
                            )
                            _quality_judge_hit = any(
                                token in _judge_reason
                                for token in (
                                    "잘림", "잘렸", "동일", "중복", "유사",
                                    "자연스러움", "정책", "빈도", "화제전환", "메타",
                                )
                            )
                            if attempt < 2:
                                q_log(
                                    f"[BATCH] 🧠 [{wave}] Judge 거부: "
                                    f"{_judge_reason[:60]} — 재시도 ({attempt+1}/3)"
                                )
                                continue
                            else:
                                q_log(
                                    f"[BATCH] 🧠 [{wave}] Judge 3회 거부: "
                                    f"{_judge_reason[:60]} — 이 Wave 스킵"
                                )
                                _failure_reason = _judge_reason
                                gen_title = None
                                gen_content = ""
                                break
                        # Judge가 제목 수정을 제안한 경우 적용
                        _fixed = _verdict.get("fixed_title")
                        if _fixed and isinstance(_fixed, str) and _fixed.strip():
                            q_log(f"[BATCH] 🧠 [{wave}] Judge 제목 보정: '{gen_title[:20]}' → '{_fixed[:20]}'")
                            gen_title = naturalness.ensure_question_punctuation(
                                _fixed.strip()
                            )
                            _fixed_structure_reasons = _structure_failure_reasons(
                                gen_title,
                                gen_content,
                                style_profile=style_profile,
                            )
                            if _fixed_structure_reasons:
                                _judge_reason = ", ".join(
                                    _fixed_structure_reasons
                                )
                                if attempt < 2:
                                    q_log(
                                        f"[BATCH] 🧠 [{wave}] Judge 보정 제목 구조 위반: "
                                        f"{_judge_reason} — 재시도 ({attempt+1}/3)"
                                    )
                                    continue
                                _failure_reason = (
                                    f"Judge 보정 제목 구조 위반: {_judge_reason}"
                                )
                                gen_title = None
                                gen_content = ""
                                break
                            if _title_key(gen_title) in _used_title_keys:
                                q_log(f"[BATCH] ♻️ [{wave}] Judge 보정 후 동일 제목 감지 — 재시도 ({attempt+1}/3)")
                                continue
                    except Exception as _je:
                        q_log(f"[BATCH] 🧠 [{wave}] Judge 오류 (무시): {str(_je)[:50]}")

                _last_candidate_title = gen_title
                _last_candidate_content = gen_content
                _last_candidate_comments = list(_tc_list)
                q_log(f"[BATCH] ✅ [{wave}] 생성 완료: '{gen_title[:30]}'")

                # 배치 내 중복 방지: 생성 성공 시 제목 누적
                _used_titles.append(gen_title)
                _used_title_keys.add(_title_key(gen_title))
                _successful_slot = str(_wave_plan.get("slot") or "context")
                _slot_success_counts[_successful_slot] = (
                    _slot_success_counts.get(_successful_slot, 0) + 1
                )
                _angle_key = _draft_angle_key(gen_title, gen_content)
                if _angle_key:
                    _angle_counts[_angle_key] = _angle_counts.get(_angle_key, 0) + 1
                _question_sig = naturalness.question_skeleton_signature(gen_title, gen_content)
                if _question_sig:
                    _question_skeleton_counts[_question_sig] = (
                        _question_skeleton_counts.get(_question_sig, 0) + 1
                    )
                _reaction_sig = naturalness.reaction_skeleton_signature(
                    gen_title,
                    gen_content,
                )
                if _reaction_sig:
                    _reaction_skeleton_counts[_reaction_sig] = (
                        _reaction_skeleton_counts.get(_reaction_sig, 0) + 1
                    )
                _successful_family = draft_guidance.topic_family_tokens(
                    " ".join(
                        [
                            str(_wave_plan.get("slot_text") or ""),
                            gen_title,
                            gen_content,
                        ]
                    )
                )
                if _successful_family:
                    _successful_topic_families.append(_successful_family)
                if naturalness.is_direct_question(gen_title, gen_content):
                    _direct_question_count += 1
                # 어휘 엔트로피 추적: 본문 첫 어절 수집
                _fw = gen_content.strip().split()[0] if gen_content.strip() else ""
                if _fw:
                    _batch_first_words.append(_fw)
                break

            except _cf.TimeoutError:
                q_log(f"[BATCH] ⏱️ [{wave}] 생성 타임아웃 (40s) — 이 대본 건너뜀")
                _failure_reason = "생성 시간이 제한을 초과했습니다."
                _failure_stage = "generation_timeout"
                break  # 부분 실패 허용: 이 Wave만 스킵, 다음 Wave 계속
            except RateLimitError:
                _failure_stage = "rate_limit"
                if attempt < 2:
                    backoff = 60 * (2 ** attempt)
                    q_log(f"[BATCH] ⚠️ [{wave}] Rate Limit — {backoff}초 대기 ({attempt+1}/3)...")
                    _interruptible_sleep(backoff, stop_ev)
                else:
                    q_log(f"[BATCH] ❌ [{wave}] Rate Limit 재시도 한도 초과")
                    _failure_reason = "API 호출 제한으로 생성을 완료하지 못했습니다."
            except Exception as e:
                q_log(f"[BATCH] ❌ [{wave}] 생성 오류: {str(e)[:80]}")
                _failure_reason = f"생성 오류: {str(e)[:120]}"
                _failure_stage = "generation_exception"
                _failure_detail = str(e)[:500]
                break

        scripts.append({
            "wave":             wave,
            "persona_name":     _persona["name"],
            "tone":             _wave_tone,
            "title":            gen_title or "",
            "content":          gen_content,
            "target_comments":  _tc_list,
            "_failed":          gen_title is None,
            "_rejected_title":  _last_candidate_title if gen_title is None else "",
            "_rejected_content": _last_candidate_content if gen_title is None else "",
            "_rejected_comments": _last_candidate_comments if gen_title is None else [],
            "_failure_reason":  _failure_reason if gen_title is None else "",
            "_failure_stage":   _failure_stage if gen_title is None else "",
            "_failure_detail":  _failure_detail if gen_title is None else "",
            "_failure_attempts": _failure_attempts if gen_title is None else 0,
            "_source_slot":      str(_wave_plan.get("slot") or ""),
        })

    ok_count = sum(1 for s in scripts if not s.get("_failed"))
    q_log(f"[BATCH] 🎬 대본 생성 완료 — 성공 {ok_count}/{len(scripts)}개")

    # ── Wave 대본 요약 (런타임 로그 전용 — 테스트/일반 모드 공용) ───────────
    # 어떤 페르소나가 어떤 제목을 생성했는지 한눈에 파악 가능.
    _valid_scripts = [s for s in scripts if not s.get("_failed")]
    _failed_cnt = len(scripts) - len(_valid_scripts)
    _fail_tag = f"  (실패 {_failed_cnt}개)" if _failed_cnt else ""
    _purpose_target = gallery_purpose.target_count(gallery_id, actual_count)
    _purpose_count = sum(
        1
        for script in _valid_scripts
        if gallery_purpose.text_matches(
            gallery_id,
            str(script.get("title") or ""),
            str(script.get("content") or ""),
        )
    )
    if _purpose_target:
        q_log(
            "[QC] 본래 주제 비율 — "
            f"{_purpose_count}/{len(_valid_scripts)}개 "
            f"(배치 목표 {_purpose_target}/{actual_count}개)"
        )
    try:
        _runtime_log_file.write(f"\n{'═' * 58}\n")
        _runtime_log_file.write(f"  대본 목록 — 생성 {len(_valid_scripts)}개{_fail_tag}\n")
        _runtime_log_file.write(f"{'═' * 58}\n")
        for _i, _s in enumerate(_valid_scripts, 1):
            _tn = (_s.get("tone") or "")[:14].ljust(14)
            _tt = (_s.get("title") or "")[:50]
            _runtime_log_file.write(f"  {_i:2}. [{_tn}]  {_tt}\n")
        _runtime_log_file.write("\n")
        _runtime_log_file.flush()
    except Exception:
        pass

    # ── 배치 품질 지표 자동 집계 ───────────────────────────────────────────
    if _used_titles:
        from collections import Counter as _QCtr
        _q_toks = [t.strip().split()[0] for t in _used_titles if t.strip()]
        _q_freq = _QCtr(_q_toks)
        _q_total = len(_q_toks)
        # HHI (Herfindahl-Hirschman Index): 0~1, 높을수록 집중
        _q_hhi = sum((c / _q_total) ** 2 for c in _q_freq.values()) if _q_total else 0
        _q_unique_ratio = len(_q_freq) / _q_total if _q_total else 0
        _q_meta_count = sum(
            1 for s in scripts
            if not s.get("_failed")
            and (
                naturalness.has_generic_meta_reaction(s.get("title", ""), s.get("content", ""))
                or naturalness.has_hard_meta_reaction(s.get("title", ""), s.get("content", ""))
            )
        )
        _q_meta_rate = _q_meta_count / ok_count if ok_count else 0
        if _q_hhi <= 0.25:
            _hhi_label = "양호"
        elif _q_hhi <= 0.35:
            _hhi_label = "주의"
        else:
            _hhi_label = "위험"
        q_log(
            f"[QC] 📊 배치 품질 — "
            f"HHI={_q_hhi:.3f} ({_hhi_label}) | "
            f"고유 소재 비율={_q_unique_ratio:.1%} | "
            f"메타 표현 {_q_meta_count}/{ok_count}개 ({_q_meta_rate:.0%})"
        )
        # 심각한 수렴 경고
        if _q_hhi > 0.35:
            q_log(f"[QC] ⚠️ 화제 집중도 위험 수준 (HHI={_q_hhi:.3f}) — 다양성 시스템 점검 필요")
        if _q_meta_rate > 0.3:
            q_log(f"[QC] ⚠️ 메타 표현 과다 ({_q_meta_rate:.0%}) — 프롬프트 규칙 점검 필요")
        if _angle_counts:
            _angle_total = sum(_angle_counts.values())
            _angle_hhi = sum((count / _angle_total) ** 2 for count in _angle_counts.values()) if _angle_total else 0
            _angle_top = ", ".join(
                f"{key} {count}개"
                for key, count in sorted(_angle_counts.items(), key=lambda item: -item[1])[:3]
            )
            q_log(f"[QC] 🎚️ 발화 각도 분포 — HHI={_angle_hhi:.3f} | {_angle_top}")
        if _question_skeleton_counts:
            _shape_total = sum(_question_skeleton_counts.values())
            _shape_hhi = (
                sum((count / _shape_total) ** 2 for count in _question_skeleton_counts.values())
                if _shape_total
                else 0
            )
            _shape_top = ", ".join(
                f"{naturalness.question_skeleton_label(key)} {count}개"
                for key, count in sorted(
                    _question_skeleton_counts.items(),
                    key=lambda item: -item[1],
                )[:3]
            )
            q_log(f"[QC] 🧩 질문 골격 분포 — HHI={_shape_hhi:.3f} | {_shape_top}")

    # ── 어휘 엔트로피 최종 저장 ─────────────────────────────────────────────
    # 이 배치에서 수집된 first_words를 슬라이딩 윈도우에 추가.
    # 다음 사이클에서 get_banned_starts()로 읽어 자동 금지어로 주입.
    if _batch_first_words:
        _new_banned_starts = _cm.update_vocab(_mem, _batch_first_words)
        if _new_banned_starts:
            q_log(
                f"[CYCLE-MEM] 📊 어휘 수렴 감지 — 다음 사이클 자동 금지어: {_new_banned_starts}"
            )

    # ── 제목 키워드 엔트로피 추적 ────────────────────────────────────────────
    # 성공한 대본의 제목 첫 토큰을 title_vocab_window에 추가.
    # 다음 사이클에서 get_banned_title_keywords()로 읽어 반복 소재 차단.
    _ok_titles = [s["title"] for s in scripts if not s.get("_failed") and s.get("title")]
    if _ok_titles:
        _new_banned_title_kws = _cm.update_title_vocab(_mem, _ok_titles)
        if _new_banned_title_kws:
            q_log(
                f"[CYCLE-MEM] 📰 제목 키워드 수렴 감지 — 다음 사이클 금지어: {_new_banned_title_kws}"
            )

    _cm.save(_mem_root)  # 어휘·제목 윈도우 통합 1회 저장

    # 디스크 로그 마무리
    try:
        _ok = sum(1 for s in scripts if not s.get("_failed"))
        _fail = sum(1 for s in scripts if s.get("_failed"))
        _runtime_log_file.write(f"\n=== 배치 완료: 성공 {_ok}개 / 실패 {_fail}개 ===\n")
        _runtime_log_file.close()
    except Exception:
        pass

    rehearsal_intel: dict = {}
    rehearsal_next_topic = ""
    if rehearsal:
        cycle_limit = rehearsal_flow.normalize_cycle_limit(rehearsal_cycle_limit)
        anchor_count = len(rehearsal_anchor_posts or ())
        q_log(
            f"[REHEARSAL] 사이클 {rehearsal_cycle}/{cycle_limit} 원고 재분석 중 "
            f"— 원고 + 원본 앵커 {anchor_count}개 사용"
        )
        try:
            rehearsal_intel = brain.analyze_trend(
                rehearsal_flow.build_analysis_payload(
                    scripts,
                    gallery_id=gallery_id,
                    anchor_posts=rehearsal_anchor_posts or (),
                    anchor_topic=rehearsal_anchor_topic,
                )
            )
            rehearsal_next_topic = rehearsal_flow.build_next_topic(
                rehearsal_intel,
                scripts,
                gallery_id=gallery_id,
                anchor_posts=rehearsal_anchor_posts or (),
                anchor_topic=rehearsal_anchor_topic,
            )
            _hot_topics = rehearsal_intel.get("hot_topics") or []
            _hot_topic_text = " / ".join(str(item).strip() for item in _hot_topics[:4] if str(item).strip())
            _guidance_preview = re.sub(
                r"\s+",
                " ",
                str(rehearsal_intel.get("generation_guidance") or "").strip(),
            )[:160]
            q_log(
                f"[REHEARSAL] 사이클 {rehearsal_cycle}/{cycle_limit} 분석 완료"
            )
            if _hot_topic_text:
                q_log(
                    f"[REHEARSAL] 사이클 {rehearsal_cycle}/{cycle_limit} 다음 주제: "
                    f"{_hot_topic_text}"
                )
            if _guidance_preview:
                q_log(
                    f"[REHEARSAL] 사이클 {rehearsal_cycle}/{cycle_limit} 작문 지시 갱신: "
                    f"{_guidance_preview}"
                )
        except Exception as exc:
            rehearsal_next_topic = rehearsal_flow.build_next_topic(
                {},
                scripts,
                gallery_id=gallery_id,
            )
            q_log(
                f"[REHEARSAL] 분석 실패 — 원고 제목 기반 안전 폴백 사용: "
                f"{str(exc)[:140]}"
            )

    log_q.put(
        worker_contracts.worker_message(
            worker_contracts.MSG_BATCH_DONE,
            scripts=scripts,
            rehearsal_cycle=rehearsal_cycle if rehearsal else None,
            rehearsal_cycle_limit=(
                rehearsal_flow.normalize_cycle_limit(rehearsal_cycle_limit)
                if rehearsal
                else None
            ),
            rehearsal_intel=rehearsal_intel,
            rehearsal_next_topic=rehearsal_next_topic,
        )
    )


def _batch_gen_worker_guarded(
    log_q: queue.Queue,
    stop_ev: threading.Event,
    **kwargs,
) -> None:
    """Ensure an unexpected worker crash cannot strand infinite mode."""

    gallery_id = str(kwargs.get("gallery_id") or "").strip()
    memory_before = _cm.load()
    gallery_memory_before = copy.deepcopy(
        _cm.get_gallery_memory(memory_before, gallery_id)
    )
    try:
        _batch_gen_worker(log_q=log_q, stop_ev=stop_ev, **kwargs)
    except BaseException as exc:
        try:
            memory_after = _cm.load()
            if gallery_id:
                memory_after.setdefault("galleries", {})[gallery_id] = gallery_memory_before
            else:
                memory_after.update(gallery_memory_before)
            _cm.save(memory_after)
        except Exception:
            pass
        try:
            log_q.put(
                worker_contracts.worker_message(
                    worker_contracts.MSG_LOG,
                    data=f"[BATCH] ❌ 워커 비정상 종료: {type(exc).__name__}: {str(exc)[:120]}",
                )
            )
            log_q.put(
                worker_contracts.worker_message(
                    worker_contracts.MSG_BATCH_DONE,
                    scripts=[],
                    fatal_error=f"{type(exc).__name__}: {str(exc)[:200]}",
                )
            )
        except Exception:
            pass


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
    wave_interval_min: int = 1,
    wave_interval_max: int = 3,
    wave_test_mode: bool = False,
    publish_interval_minutes: int | None = None,
    ai_disclosure_enabled: bool = False,
    ai_disclosure_marker: str = operator_settings.DEFAULT_PUBLIC_AI_MARKER,
    ai_comment_watch_limit: int = 5,
) -> None:
    """백그라운드 스레드: 검수 완료된 대본을 Wave 간 쿨타임에 맞춰 순차 발행.
    메시지 포맷은 기존 _swarm_worker와 동일 (log / preview / stat / done).
    wave_test_mode=True 시 분 단위 설정값을 그대로 초로 처리 (빠른 사이클 검증용).
    """

    def q_log(msg: str) -> None:
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_LOG, data=msg))

    def q_preview(title: str, content: str, wave: int, status: str) -> None:
        log_q.put(worker_contracts.worker_message(
            worker_contracts.MSG_PREVIEW,
            title=title,
            content=content,
            wave=wave,
            status=status,
        ))

    def q_stat(success: int = 0, fail: int = 0) -> None:
        log_q.put(worker_contracts.worker_message(
            worker_contracts.MSG_STAT,
            success=success,
            fail=fail,
        ))

    # DB 초기화 안전망: _batch_gen_worker가 init_db()를 호출하지만
    # 스레드 타이밍 문제나 재시작 직후 _post_exec_worker가 먼저 실행될 경우 방어.
    database.init_db()
    publish_settings = operator_settings.PublishSettings(
        publish_interval_minutes=operator_settings.normalize_publish_interval_minutes(
            publish_interval_minutes or 3
        ),
        ai_disclosure_enabled=False,
        ai_disclosure_marker=operator_settings.DEFAULT_PUBLIC_AI_MARKER,
        ai_comment_watch_limit=operator_settings.normalize_ai_comment_watch_limit(
            ai_comment_watch_limit
        ),
    )
    try:
        _known_ai_posts_for_comments = database.get_ai_post_nos(gallery_id)
    except Exception:
        _known_ai_posts_for_comments = set()

    try:
        _account_pool = load_accounts()
    except (FileNotFoundError, ValueError) as _ae:
        q_log(f"❌ 계정 로드 실패 — 연재 중단: {str(_ae)[:120]}")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_DONE))
        return

    _account_queue: list[dict] = list(_account_pool)
    valid_scripts = [s for s in scripts if not s.get("_failed") and s.get("title")]

    if not valid_scripts:
        q_log("[EXEC] ⚠️ 발행 가능한 대본이 없습니다.")
        log_q.put(worker_contracts.worker_message(worker_contracts.MSG_DONE))
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
        post_title, post_content = gen_title, gen_content

        q_log(f"═══════ WAVE {wave} ({i + 1}/{len(valid_scripts)}) ═══════")
        q_log(f"[W{wave}] 🚀 포스팅 시작 → {gallery_type}/{gallery_id}")
        q_preview(post_title, post_content, wave, "POSTING...")

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
                poster.auto_post(gallery_id=gallery_id, title=post_title,
                                 content=post_content, account=_wave_account,
                                 log_callback=q_log)
            )
        finally:
            loop.close()
            asyncio.set_event_loop(None)

        if post_result["success"]:
            q_stat(success=1)
            q_log(f"[W{wave}] 🎉 포스팅 성공! ({post_result['message']})")
            q_preview(post_title, post_content, wave, "✅ POSTED")
            _posted_no = str(post_result.get("post_no") or "").strip()
            if _posted_no:
                _watch_ai_post_comments_once(
                    gallery_id=gallery_id,
                    gallery_type=gallery_type,
                    post_no=_posted_no,
                    log_callback=q_log,
                )
        else:
            q_stat(fail=1)
            q_log(f"[W{wave}] ❌ 포스팅 실패: {post_result['message']}")
            q_preview(post_title, post_content, wave, "❌ FAILED")

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
                if comment_targets.should_skip_public_comment(
                    _tc,
                    known_ai_posts=_known_ai_posts_for_comments,
                ):
                    q_log(
                        f"[W{wave}] [SAFE] #{_post_no} AI 작성글 댓글 후보 — "
                        "시너지 리허설 전용으로 실제 발행 생략"
                    )
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

        # Wave 간 쿨타임 (사용자 설정 범위 내 랜덤)
        if i < len(valid_scripts) - 1 and not stop_ev.is_set():
            interval_minutes = publish_settings.publish_interval_minutes
            if wave_test_mode:
                if interval_minutes > 0:
                    wait_sec = max(1, interval_minutes)
                    q_log(f"[TEST] 🧪 다음 WAVE까지 {wait_sec}초 대기... (고정 간격 테스트)")
                else:
                    # 🧪 테스트 모드: 분 설정값을 그대로 초로 처리 (1분→1초)
                    _lo = max(1, wave_interval_min)
                    _hi = max(_lo, wave_interval_max)
                    wait_sec = random.randint(_lo, _hi)
                    q_log(f"[TEST] 🧪 다음 WAVE까지 {wait_sec}초 대기... (테스트 모드: {wave_interval_min}~{wave_interval_max}초)")
            else:
                if interval_minutes > 0:
                    wait_sec = max(30, interval_minutes * 60 - _comment_elapsed)
                    q_log(f"[EXEC] ☕ 다음 WAVE까지 {wait_sec}초 대기... ({interval_minutes}분 고정 간격)")
                else:
                    _lo = max(30, wave_interval_min * 60)
                    _hi = max(_lo, wave_interval_max * 60)
                    _base_wait = random.randint(_lo, _hi)
                    wait_sec   = max(30, _base_wait - _comment_elapsed)
                    q_log(f"[EXEC] ☕ 다음 WAVE까지 {wait_sec}초 대기... ({wave_interval_min}~{wave_interval_max}분 범위)")
            _interruptible_sleep(wait_sec, stop_ev)

    if publish_settings.ai_comment_watch_limit > 0 and not stop_ev.is_set():
        _watch_recent_ai_post_comments(
            gallery_id=gallery_id,
            gallery_type=gallery_type,
            limit=publish_settings.ai_comment_watch_limit,
            log_callback=q_log,
        )
    q_log(f"═══════ EXECUTION COMPLETE — {len(valid_scripts)} WAVES FIRED ═══════")
    log_q.put(worker_contracts.worker_message(worker_contracts.MSG_DONE))


# ══════════════════════════════════════════════════════════════════════════════
# 헬퍼: 테스트 모드 사이클 요약 포맷터
# ══════════════════════════════════════════════════════════════════════════════


def _build_test_summary(
    scripts: list,
    intel: dict | None,
    wave_num: int,
    mem: dict | None = None,
) -> str:
    """테스트 모드 Wave 사이클 요약 문자열 생성 (st.code 출력 + 로그 파일 공용)."""
    return ui_formatters.build_test_summary(scripts, intel, wave_num, mem)


def _append_test_log(summary: str, log_path: "Path") -> None:  # type: ignore[name-defined]
    """테스트 요약을 log_path에 append. 실패 시 무시."""
    return append_text_log(summary, log_path)


# ══════════════════════════════════════════════════════════════════════════════
# 헬퍼: 무한 모드 자동 포스팅 워커 시작 (검수 게이트 우회)
# ══════════════════════════════════════════════════════════════════════════════


def _auto_launch_swarm(ss: "st.session_state", scripts: list) -> None:  # type: ignore[name-defined]
    """무한 모드 전용: 검수 게이트 없이 포스팅 워커를 즉시 시작.

    _review_board_fragment의 '✅ 대본 최종 승인' 버튼 핸들러 로직을 DRY하게 추출.
    유효 대본(not _failed)이 0개면 즉시 다음 배치 사이클로 넘어가 실패 루프를 방지.
    테스트 모드(wave_test_mode=True)이면 포스팅 없이 즉시 다음 배치 생성으로 넘어간다.
    """
    _cfg = ss.get("_batch_gen_config", {})

    # ── 테스트 모드: 포스팅 완전 생략 → LLM 생성 → 여론 갱신 루프만 반복 ──
    if _cfg.get("wave_test_mode"):
        import datetime as _dt
        from pathlib import Path as _Path

        _wave_n = ss.get("_test_wave_counter", 0) + 1
        ss["_test_wave_counter"] = _wave_n

        # 세션 최초: 로그 파일 경로 생성
        if not ss.get("_test_log_path"):
            _log_ts  = _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            _log_dir = _Path(__file__).parent / "logs"
            _log_dir.mkdir(exist_ok=True)
            ss["_test_log_path"] = str(_log_dir / f"test_{_log_ts}.txt")

        # 헤더 기록: 파일이 아직 없거나 비어있을 때만 (Streamlit rerun 중복 방지)
        _log_file = _Path(ss["_test_log_path"])
        if not _log_file.exists() or _log_file.stat().st_size == 0:
            _log_ts_disp = _log_file.stem.replace("test_", "")
            _hdr = f"{'=' * 58}\n  Echo Chamber TEST LOG  ·  시작: {_log_ts_disp}\n{'=' * 58}\n\n"
            _append_test_log(_hdr, ss["_test_log_path"])

        _intel   = ss.get("intel_result")
        _mem_now_root = _cm.load()   # 최신 cycle_memory 로드 (배치가 방금 저장한 상태)
        _mem_now = _cm.get_gallery_memory(
            _mem_now_root,
            str(_cfg.get("gallery_id", "") or ""),
        )
        _summary = _build_test_summary(scripts, _intel, _wave_n, mem=_mem_now)

        if not isinstance(ss.get("test_summaries"), list):
            ss["test_summaries"] = []
        ss.test_summaries.append(_summary)

        # 로그 파일 append
        _log_path = ss.get("_test_log_path")
        if _log_path:
            _append_test_log(_summary, _log_path)

        ss.swarm_log.append(
            f"[TEST] 🧪 WAVE {_wave_n} 요약 → {_Path(_log_path).name if _log_path else '?'}"
        )
        _start_next_batch(ss)
        return

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
    ss.swarm_log.append(
        f"[∞] 무한모드 — 검토 단계를 건너뛰고 {len(valid)}개 원고 발행을 시작합니다."
    )

    threading.Thread(
        target=_post_exec_worker,
        kwargs={
            "log_q":              _post_q,
            "stop_ev":            _post_ev,
            "scripts":            scripts,
            "gallery_id":         _cfg.get("gallery_id", ""),
            "gallery_type":       _cfg.get("gallery_type", "mgallery"),
            "headless":           _cfg.get("headless", True),
            "wave_interval_min":  _cfg.get("wave_interval_min", 1),
            "wave_interval_max":  _cfg.get("wave_interval_max", 3),
            "wave_test_mode":     _cfg.get("wave_test_mode", False),
            "publish_interval_minutes": _cfg.get("publish_interval_minutes"),
            "ai_disclosure_enabled": False,
            "ai_disclosure_marker": operator_settings.DEFAULT_PUBLIC_AI_MARKER,
            "ai_comment_watch_limit": operator_settings.normalize_ai_comment_watch_limit(
                _cfg.get("ai_comment_watch_limit", operator_settings.DEFAULT_AI_COMMENT_WATCH_LIMIT)
            ),
        },
        daemon=True,
    ).start()


def _launch_review_scripts(ss: "st.session_state") -> str | None:  # type: ignore[name-defined]
    """Start publishing the currently reviewed scripts.

    Returns an error message for the UI when launch cannot start.
    """

    scripts = ss.get("review_scripts", []) or []
    valid = [s for s in scripts if not s.get("_failed")]
    if not valid:
        return "발행 가능한 원고가 없습니다. 폐기 후 다시 생성하세요."

    try:
        load_accounts()
    except (FileNotFoundError, ValueError) as err:
        return f"accounts.txt 로드 실패: {err}"

    _post_q: queue.Queue = queue.Queue()
    _post_ev: threading.Event = threading.Event()
    _previous_draft_log = list(ss.get("swarm_log", []))[-180:]

    ss.review_ready = False
    ss.swarm_running = True
    ss.swarm_queue = _post_q
    ss.swarm_stop_event = _post_ev
    ss.swarm_log = _previous_draft_log + ["[PUBLISH] 검토 완료 — 발행 시작"]
    ss.swarm_preview_title = ""
    ss.swarm_preview_content = ""
    ss.swarm_wave_total = len(valid)
    ss.swarm_wave_current = 0
    ss.last_fired = True

    cfg = ss.get("_batch_gen_config", {})
    observability.append_event(
        ss,
        kind="publish_start",
        title="reviewed drafts publish start",
        detail=f"ready={len(valid)} gallery={cfg.get('gallery_id', '')}",
        status="running",
        metrics={"ready": len(valid)},
    )
    threading.Thread(
        target=_post_exec_worker,
        kwargs={
            "log_q": _post_q,
            "stop_ev": _post_ev,
            "scripts": scripts,
            "gallery_id": cfg.get("gallery_id", ""),
            "gallery_type": cfg.get("gallery_type", "mgallery"),
            "headless": cfg.get("headless", True),
            "wave_interval_min": cfg.get("wave_interval_min", 1),
            "wave_interval_max": cfg.get("wave_interval_max", 3),
            "wave_test_mode": cfg.get("wave_test_mode", False),
            "publish_interval_minutes": cfg.get("publish_interval_minutes"),
            "ai_disclosure_enabled": False,
            "ai_disclosure_marker": operator_settings.DEFAULT_PUBLIC_AI_MARKER,
            "ai_comment_watch_limit": operator_settings.normalize_ai_comment_watch_limit(
                cfg.get("ai_comment_watch_limit", operator_settings.DEFAULT_AI_COMMENT_WATCH_LIMIT)
            ),
        },
        daemon=True,
    ).start()
    return None


# 헬퍼: 다음 배치 생성 시작 (무한 모드 자동 재배치용)
# ══════════════════════════════════════════════════════════════════════════════


# Phase 11: _batch_gen_worker가 받는 파라미터 화이트리스트.
# _batch_gen_config는 _post_exec_worker용 'headless' 등 여분 키를 포함하므로
# {**cfg} 언팩 방식은 새 키가 추가될 때마다 TypeError → daemon 스레드 즉사를 유발하는
# 취약 패턴이다. 명시적 허용 키 집합으로 필터링하여 미래 config 확장에도 안전하게 보호.
_BATCH_GEN_PARAMS: frozenset = worker_contracts.BATCH_GEN_PARAMS


def _start_next_batch(
    ss: "st.session_state",  # type: ignore[name-defined]
    *,
    auto_refresh: bool | None = None,
) -> None:
    """저장된 _batch_gen_config를 이용해 다음 배치 생성 워커를 즉시 시작.

    Phase 11 버그픽스:
      _batch_gen_config의 'headless' 키가 {**cfg} 언팩으로 _batch_gen_worker에
      그대로 전달되어 TypeError → daemon 스레드 즉사 → 무한 루프 단절 버그 수정.
      _BATCH_GEN_PARAMS 화이트리스트로 허용 키만 필터링하여 전달.
    """
    cfg = dict(ss.get("_batch_gen_config", {}) or {})
    if not cfg:
        return
    is_rehearsal = bool(cfg.get("wave_test_mode"))
    if is_rehearsal:
        cfg["infinite"] = False
        cfg["rehearsal"] = True
        cfg["wave_count"] = 10
    elif ss.get("swarm_infinite"):
        cfg["infinite"] = True
        cfg["wave_count"] = 10
    ss["_batch_gen_config"] = cfg
    ss["_infinite_refill_scripts"] = []
    ss["_infinite_refill_round"] = 0
    _bgq  = queue.Queue()
    _bgev = threading.Event()
    ss.batch_generating     = True
    ss.batch_gen_queue      = _bgq
    ss.batch_gen_stop_event = _bgev
    # Phase 8: 로그 초기화 대신 사이클 구분선 추가 — 이전 사이클 기록 보존
    _cycle_num = int(cfg.get("rehearsal_cycle") or 0) if is_rehearsal else (
        getattr(ss, "_batch_cycle_count", 0) + 1
    )
    ss._batch_cycle_count   = _cycle_num
    observability.append_event(
        ss,
        kind="cycle_start",
        title=f"cycle {_cycle_num} generation start",
        detail=f"target={cfg.get('wave_count', 10)} rehearsal={is_rehearsal}",
        status="running",
        cycle=_cycle_num,
        metrics={"target": cfg.get("wave_count", 10)},
    )
    _retention_limit = _current_log_retention_limit(ss)
    _prev_log = list(getattr(ss, "swarm_log", []))[-_retention_limit:]
    if is_rehearsal:
        cycle_limit = rehearsal_flow.normalize_cycle_limit(
            cfg.get("rehearsal_cycle_limit")
        )
        ss.swarm_log = _prev_log + [
            f"[REHEARSAL] 사이클 {_cycle_num}/{cycle_limit} 시작 "
            "— 직전 리허설 원고 분석 결과로 10개를 생성합니다."
        ]
    else:
        ss.swarm_log = _prev_log + [
            f"[∞] 무한모드 CYCLE {_cycle_num} 시작 — 다음 원고 묶음을 자동 생성합니다."
        ]
    ss.swarm_wave_current   = 0
    ss.swarm_wave_total     = cfg.get("wave_count", 10)
    # Phase 11 핵심 픽스: headless 등 worker 미지원 키 차단 — 화이트리스트 필터
    threading.Thread(
        target=_batch_gen_worker_guarded,
        kwargs=worker_contracts.build_batch_gen_worker_kwargs(
            cfg,
            log_q=_bgq,
            stop_ev=_bgev,
            auto_refresh=(not is_rehearsal) if auto_refresh is None else auto_refresh,
        ),
        daemon=True,
    ).start()


def _handle_rehearsal_batch_done(
    ss: "st.session_state",  # type: ignore[name-defined]
    message: dict,
) -> str:
    """Store one rehearsal cycle and start the next finite cycle when needed."""

    cfg = dict(ss.get("_batch_gen_config", {}) or {})
    cycle = max(1, int(message.get("rehearsal_cycle") or cfg.get("rehearsal_cycle") or 1))
    cycle_limit = rehearsal_flow.normalize_cycle_limit(
        message.get("rehearsal_cycle_limit")
        or cfg.get("rehearsal_cycle_limit")
    )
    scripts = list(message.get("scripts") or [])
    intel = dict(message.get("rehearsal_intel") or {})
    next_topic = str(message.get("rehearsal_next_topic") or "").strip()
    hot_topics = [
        str(item).strip()
        for item in (intel.get("hot_topics") or [])
        if str(item).strip()
    ]
    guidance_preview = re.sub(
        r"\s+",
        " ",
        str(intel.get("generation_guidance") or "").strip(),
    )[:160]
    valid_count = sum(1 for item in scripts if not item.get("_failed"))
    failed_count = sum(1 for item in scripts if item.get("_failed"))
    observability.record_cycle(
        ss,
        cycle=cycle,
        mode="rehearsal",
        scripts=scripts,
        target_count=int(cfg.get("wave_count", 10) or 10),
        gallery_id=str(cfg.get("gallery_id") or ""),
        status="complete" if cycle >= cycle_limit else "next",
    )
    cycle_log_lines = [
        f"[REHEARSAL] 사이클 {cycle}/{cycle_limit} 생성 결과 — 성공 {valid_count}개 / 실패 {failed_count}개",
        f"[REHEARSAL] 사이클 {cycle}/{cycle_limit} 주제와 작문 지시 재분석 완료",
    ]
    if hot_topics:
        cycle_log_lines.append(
            f"[REHEARSAL] 사이클 {cycle}/{cycle_limit} 다음 주제 — "
            + " / ".join(hot_topics[:4])
        )
    if guidance_preview:
        cycle_log_lines.append(
            f"[REHEARSAL] 사이클 {cycle}/{cycle_limit} 작문 지시 — {guidance_preview}"
        )

    if not isinstance(ss.get("rehearsal_runs"), list):
        ss["rehearsal_runs"] = []
    ss.rehearsal_runs.append(
        {
            "cycle": cycle,
            "cycle_limit": cycle_limit,
            "expected_count": int(cfg.get("wave_count", 10) or 10),
            "scripts": copy.deepcopy(scripts),
            "intel": copy.deepcopy(intel),
            "next_topic": next_topic,
            "log_lines": copy.deepcopy(cycle_log_lines),
        }
    )
    ss["_test_wave_counter"] = cycle
    summary = _build_test_summary(
        scripts,
        intel or ss.get("intel_result"),
        cycle,
        mem=None,
    )
    if not isinstance(ss.get("test_summaries"), list):
        ss["test_summaries"] = []
    ss.test_summaries.append(summary)

    ss.swarm_log.extend(cycle_log_lines)

    if cycle >= cycle_limit or ss.get("_batch_fatal_error"):
        ss["_rehearsal_complete"] = True
        ss.review_ready = bool(scripts)
        ss.batch_generating = False
        ss.swarm_log.append(
            f"[REHEARSAL] 전체 {cycle_limit}사이클 완료 — 발행 없이 종료했습니다."
        )
        return "complete"

    if not next_topic:
        next_topic = rehearsal_flow.build_next_topic(
            intel,
            scripts,
            gallery_id=str(cfg.get("gallery_id") or ""),
            anchor_posts=cfg.get("rehearsal_anchor_posts") or (),
            anchor_topic=str(cfg.get("rehearsal_anchor_topic") or ""),
        )
    cfg.update(
        {
            "topic": next_topic,
            "briefing": next_topic,
            "wave_count": 10,
            "infinite": False,
            "rehearsal": True,
            "rehearsal_cycle": cycle + 1,
            "rehearsal_cycle_limit": cycle_limit,
            "rehearsal_anchor_posts": cfg.get("rehearsal_anchor_posts") or [],
            "rehearsal_anchor_topic": str(cfg.get("rehearsal_anchor_topic") or ""),
        }
    )
    ss["_batch_gen_config"] = cfg
    ss.review_ready = False
    _start_next_batch(ss, auto_refresh=False)
    return "next"


def _start_infinite_refill_batch(
    ss: "st.session_state",  # type: ignore[name-defined]
    missing: int,
) -> None:
    """Generate only the missing drafts before an infinite-mode publish."""

    cfg = dict(ss.get("_batch_gen_config", {}) or {})
    if not cfg or missing <= 0:
        return
    gallery_id = str(cfg.get("gallery_id") or "").strip()
    target = max(1, int(cfg.get("wave_count", 10) or 10))
    purpose_target = gallery_purpose.target_count(gallery_id, target)
    purpose_count = sum(
        1
        for script in ss.get("_infinite_refill_scripts", [])
        if isinstance(script, dict)
        and not script.get("_failed")
        and gallery_purpose.text_matches(
            gallery_id,
            str(script.get("title") or ""),
            str(script.get("content") or ""),
        )
    )
    purpose_missing = max(0, purpose_target - purpose_count)
    purpose_only = purpose_missing > 0
    refill_count = min(int(missing), purpose_missing) if purpose_only else int(missing)
    has_purpose_draft = any(
        gallery_purpose.text_matches(
            gallery_id,
            str(script.get("title") or ""),
            str(script.get("content") or ""),
        )
        for script in ss.get("_infinite_refill_scripts", [])
        if isinstance(script, dict)
    )
    refill_cfg = {
        **cfg,
        "wave_count": refill_count,
        "infinite": False,
        "purpose_slot_enabled": not has_purpose_draft or purpose_only,
        "purpose_only": purpose_only,
        "is_refill": True,
    }
    refill_round = int(ss.get("_infinite_refill_round", 0) or 0) + 1
    ss["_infinite_refill_round"] = refill_round
    refill_q: queue.Queue = queue.Queue()
    refill_ev = threading.Event()
    ss.batch_generating = True
    ss.batch_gen_queue = refill_q
    ss.batch_gen_stop_event = refill_ev
    if purpose_only:
        ss.swarm_log.append(
            "[∞] 본래 주제 우선 보충 — "
            f"현재 {purpose_count}/{purpose_target}개, "
            f"이번에 {refill_count}개를 본래 주제로 생성합니다."
        )
    else:
        ss.swarm_log.append(
            f"[∞] 생성 실패 보충 {refill_round}차 — 부족한 원고 {missing}개를 다시 생성합니다."
        )
    threading.Thread(
        target=_batch_gen_worker_guarded,
        kwargs=worker_contracts.build_batch_gen_worker_kwargs(
            refill_cfg,
            log_q=refill_q,
            stop_ev=refill_ev,
            auto_refresh=False,
        ),
        daemon=True,
    ).start()


def _handle_infinite_batch_done(
    ss: "st.session_state",  # type: ignore[name-defined]
    scripts: list[dict],
) -> str:
    """Collect successful drafts and either refill, publish, or restart."""

    cfg = ss.get("_batch_gen_config", {}) or {}
    target = max(1, int(cfg.get("wave_count", 10) or 10))
    cycle_no = max(1, int(getattr(ss, "_batch_cycle_count", 0) or 1))
    is_refill_result = int(ss.get("_infinite_refill_round", 0) or 0) > 0
    generation_target = max(1, len(scripts)) if is_refill_result else target
    observability.record_cycle(
        ss,
        cycle=cycle_no,
        mode="infinite-refill" if is_refill_result else "infinite",
        scripts=scripts,
        target_count=generation_target,
        gallery_id=str(cfg.get("gallery_id") or ""),
        status="generated",
    )
    stability_report = stability.evaluate_stability(
        ss,
        scripts=scripts,
        logs=list(ss.get("swarm_log", []) or []),
        intel_result=ss.get("intel_result"),
        ai_comments=_load_ai_post_comments_for_ops(str(cfg.get("gallery_id") or "")),
    )
    if _stop_infinite_for_stability(ss, stability_report, prefix="[∞]"):
        return "stopped"
    accumulated = batch_refill.merge_valid_scripts(
        ss.get("_infinite_refill_scripts", []),
        scripts,
        target_count=target,
    )
    ss["_infinite_refill_scripts"] = accumulated
    missing = max(0, target - len(accumulated))
    if missing:
        if int(ss.get("_infinite_refill_round", 0) or 0) < 6:
            observability.append_event(
                ss,
                kind="refill_start",
                title="refill missing drafts",
                detail=f"missing={missing} target={target}",
                status="warn",
                cycle=cycle_no,
            )
            _start_infinite_refill_batch(ss, missing)
            return "refilling"
        observability.append_event(
            ss,
            kind="cycle_restart",
            title="stop after refill limit",
            detail=f"ready={len(accumulated)}/{target}",
            status="critical",
            cycle=cycle_no,
        )
        ss["swarm_infinite"] = False
        ss["_ops_last_stop_reason"] = (
            f"보충 생성 한도 도달: {len(accumulated)}/{target}개만 준비됨"
        )
        cfg = dict(ss.get("_batch_gen_config", {}) or {})
        cfg["infinite"] = False
        ss["_batch_gen_config"] = cfg
        ss.swarm_log.append(
            f"[∞] 보충 생성 한도 도달 — {len(accumulated)}/{target}개. "
            "부분 발행하지 않고 무한 실행을 멈춥니다."
        )
        return "stopped"

    ready = batch_refill.renumber_scripts(accumulated)[:target]
    ss["_infinite_refill_scripts"] = []
    ss["_infinite_refill_round"] = 0
    ss.review_scripts = ready
    observability.append_event(
        ss,
        kind="publish_start",
        title="draft batch ready for publish",
        detail=f"ready={len(ready)}/{target}",
        status="ok",
        cycle=cycle_no,
    )
    ss.swarm_log.append(f"[∞] 원고 {target}개 충원 완료 — 발행을 시작합니다.")
    _auto_launch_swarm(ss, ready)
    return "publishing"


# ══════════════════════════════════════════════
# Terminal HTML 렌더러
# ══════════════════════════════════════════════
def render_terminal(logs: list, height_px: int = 400) -> str:
    rows: list[str] = []
    for raw_line in list(logs)[-160:]:
        line = str(raw_line)
        css = "studio-log-line"
        if any(token in line for token in ("ERROR", "FAIL", "실패")):
            css += " is-error"
        elif any(token in line for token in ("WARN", "WAIT", "RETRY", "대기")):
            css += " is-warn"
        elif any(token in line for token in ("OK", "DONE", "COMPLETE", "완료")):
            css += " is-ok"
        rows.append(f'<div class="{css}">{_html.escape(line)}</div>')
    body = "\n".join(rows) if rows else '<div class="studio-log-line is-muted">아직 로그가 없습니다.</div>'
    return f'<div class="studio-terminal" style="height:{height_px}px">{body}</div>'


def render_activity_panel(logs: list, *, title: str = "활동", height_px: int = 220, limit: int = 10) -> str:
    rows: list[str] = []
    all_logs = list(logs or [])
    recent = [str(line) for line in all_logs[-limit:]]
    count_label = (
        f"최근 {len(recent)}/{len(all_logs)}개"
        if len(all_logs) > len(recent)
        else f"최근 {len(recent)}개"
    )
    for line in recent:
        css = "activity-line"
        if any(token in line for token in ("ERROR", "FAIL", "실패", "중단")):
            css += " is-error"
        elif any(token in line for token in ("WARN", "WAIT", "RETRY", "대기")):
            css += " is-warn"
        elif any(token in line for token in ("OK", "DONE", "COMPLETE", "완료", "성공")):
            css += " is-ok"
        rows.append(f'<div class="{css}"><span></span><p>{_html.escape(line)}</p></div>')
    body = "\n".join(rows) if rows else '<div class="activity-empty">아직 활동이 없습니다.</div>'
    return (
        '<style>'
        'body{margin:0;background:transparent;font-family:"Pretendard Variable","SUIT Variable","Noto Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif;}'
        '*{box-sizing:border-box;transition-duration:0s!important;animation-duration:0s!important;}'
        '.activity-panel{border:1px solid #E2E8F0;border-radius:18px;background:#fff;box-shadow:0 4px 20px -2px rgba(79,70,229,.10);overflow:hidden;padding:16px;display:grid;grid-template-rows:auto minmax(0,1fr);}'
        '.activity-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding-bottom:8px;border-bottom:1px solid #E2E8F0;}'
        '.activity-head b{color:#0F172A;font-weight:850;font-size:1rem;line-height:1}.activity-head small{color:#64748B;font-weight:850;font-size:.72rem;}'
        '.activity-body{min-height:0;overflow:auto;padding-top:9px;scroll-behavior:auto;}'
        '.activity-line{display:grid;grid-template-columns:9px minmax(0,1fr);gap:12px;align-items:start;padding:6px 0;}'
        '.activity-line span{width:7px;height:7px;margin-top:8px;border-radius:999px;background:#4F46E5;}'
        '.activity-line p{margin:0;color:#334155;font-weight:760;font-size:1rem;line-height:1.62;overflow-wrap:anywhere;}'
        '.activity-line.is-ok span{background:#10B981}.activity-line.is-warn span{background:#F59E0B}.activity-line.is-error span{background:#EF4444}.activity-empty{color:#94A3B8;font-weight:800;padding:14px 0;}'
        '</style>'
        f'<div class="activity-panel" style="height:{height_px}px">'
        f'  <div class="activity-head"><b>{_html.escape(title)}</b><small>{_html.escape(count_label)}</small></div>'
        f'  <div class="activity-body" data-autoscroll="1">{body}</div>'
        '</div>'
        '<script>'
        'const bodies=document.querySelectorAll("[data-autoscroll=\\"1\\"]");'
        'for(const el of bodies){'
        '  const pin=()=>{el.scrollTop=el.scrollHeight;};'
        '  const pinBurst=()=>{pin();requestAnimationFrame(pin);setTimeout(pin,40);setTimeout(pin,140);};'
        '  pinBurst();'
        '  new MutationObserver(pinBurst).observe(el,{childList:true,subtree:true,characterData:true});'
        '}'
        '</script>'
    )


def render_activity_panel_component(
    logs: list,
    *,
    title: str = "활동",
    height_px: int = 220,
    limit: int = 10,
    key: str | None = None,
) -> None:
    """Render an auto-scrolling log panel in an iframe-backed component."""

    components.html(
        render_activity_panel(logs, title=title, height_px=height_px, limit=limit),
        height=height_px + 6,
        scrolling=False,
    )


def render_stable_progress(ratio: float, *, label: str = "") -> str:
    """Render a CSS progress bar instead of Streamlit's animated progress widget."""

    value = max(0.0, min(1.0, float(ratio or 0.0)))
    percent = round(value * 100, 1)
    label_html = f'<span>{_html.escape(label)}</span>' if label else ""
    return (
        '<div class="stable-progress">'
        f'  <div class="stable-progress-meta">{label_html}<b>{percent:.1f}%</b></div>'
        '  <div class="stable-progress-track">'
        f'    <div class="stable-progress-fill" style="width:{percent:.1f}%"></div>'
        '  </div>'
        '</div>'
    )


# ══════════════════════════════════════════════
# 대본 Plaintext 포맷터 (검수 보드 복사용)
# ══════════════════════════════════════════════
def _format_scripts_for_copy(scripts: list[dict]) -> str:
    """생성된 대본 목록을 가독성 좋은 평문(Plaintext)으로 변환.

    Review Board의 '전체 복사' 기능에서 텍스트 영역에 주입된다.
    """
    return ui_formatters.format_scripts_for_copy(scripts)


# ══════════════════════════════════════════════
# Plotly 차트 빌더 (캐시 로직은 호출부에서 관리)
# ══════════════════════════════════════════════
def _build_intel_fig(ir: dict):
    """intel_result dict에서 Plotly 키워드 빈도 차트를 생성한다."""
    return ui_formatters.build_intel_fig(ir)


def _build_ai_briefing_topic(ir: dict) -> str:
    return ui_formatters.build_briefing_topic(ir)


def _build_ai_generation_guidance(ir: dict) -> str:
    summary_for_topic = (ir.get("summary") or "").strip()
    slot_warning = (
        _validate_slot_diversity(summary_for_topic)
        if summary_for_topic else None
    )
    return ui_formatters.build_generation_guidance(
        ir,
        slot_warning=slot_warning,
    )


def _queue_ai_briefing_topic(ir: dict) -> None:
    queue_pending_ai_briefing_topic(
        st.session_state,
        topic=_build_ai_briefing_topic(ir),
        guidance=_build_ai_generation_guidance(ir),
        gallery_id=st.session_state.get("intel_gallery_id", ""),
        type_label=st.session_state.get(
            "intel_type_label",
            ui_options.DEFAULT_GALLERY_TYPE_LABEL,
        ),
    )


def _studio_clip(value: object, limit: int = 220) -> str:
    text = ui_formatters.normalize_ai_briefing_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _studio_chip_row(items: list | tuple, *, limit: int = 7) -> str:
    chips = [
        f'<span>{_html.escape(str(item))}</span>'
        for item in list(items or [])[:limit]
        if str(item).strip()
    ]
    return "".join(chips) if chips else "<em>감지된 항목 없음</em>"


def _gallery_display_name(gallery_id: object) -> str:
    gid = str(gallery_id or "").strip()
    if not gid:
        return "게시판"
    if gid in _KNOWN_GALLERY_DISPLAY_NAMES:
        return _KNOWN_GALLERY_DISPLAY_NAMES[gid]
    try:
        contexts = pm.load_json("gallery_contexts.json")
        if isinstance(contexts, dict):
            ctx = contexts.get(gid)
            if isinstance(ctx, dict) and ctx.get("gallery_name"):
                return str(ctx["gallery_name"])
    except Exception:
        pass
    return ""


def _render_clipboard_button(label: str, text: str, *, key: str) -> None:
    """Render a compact clipboard button without expanding the Streamlit layout."""

    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", key)
    payload_js = json.dumps(text or "")
    components.html(
        f"""
        <style>
            html,
            body {{
                margin: 0;
                font-family: "Pretendard Variable", "SUIT Variable", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
                background: transparent;
                overflow: hidden;
            }}
            #{safe_id}_btn {{
                width: 100%;
                height: 42px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 7px;
                border: 1px solid #C7D2FE;
                border-radius: 14px;
                background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
                color: #4F46E5;
                font-size: 13px;
                font-weight: 850;
                letter-spacing: -0.01em;
                white-space: nowrap;
                cursor: pointer;
                box-shadow: 0 7px 18px -14px rgba(79, 70, 229, 0.48);
            }}
            #{safe_id}_btn:active {{
                background: #EEF2FF;
            }}
            #{safe_id}_btn::before {{
                content: "⧉";
                font-size: 12px;
                line-height: 1;
            }}
        </style>
        <button id="{safe_id}_btn" type="button">{_html.escape(label)}</button>
        <script>
            const btn = document.getElementById("{safe_id}_btn");
            const payload = {payload_js};
            function fallbackCopy(text) {{
                const area = document.createElement("textarea");
                area.value = text;
                area.setAttribute("readonly", "");
                area.setAttribute("aria-hidden", "true");
                area.tabIndex = -1;
                area.style.position = "fixed";
                area.style.left = "-9999px";
                area.style.top = "-9999px";
                area.style.width = "1px";
                area.style.height = "1px";
                area.style.opacity = "0";
                area.style.pointerEvents = "none";
                area.style.border = "0";
                area.style.padding = "0";
                document.body.appendChild(area);
                area.focus();
                area.select();
                const copied = document.execCommand("copy");
                area.remove();
                return copied;
            }}
            btn.addEventListener("click", async () => {{
                const original = btn.textContent;
                try {{
                    if (navigator.clipboard && window.isSecureContext) {{
                        await navigator.clipboard.writeText(payload);
                    }} else if (!fallbackCopy(payload)) {{
                        throw new Error("fallback copy failed");
                    }}
                    btn.textContent = "복사됨";
                }} catch (err) {{
                    try {{
                        fallbackCopy(payload);
                        btn.textContent = "복사됨";
                    }} catch (fallbackErr) {{
                        btn.textContent = "복사 실패";
                    }}
                }}
                setTimeout(() => {{ btn.textContent = original; }}, 1100);
            }});
        </script>
        """,
        height=48,
    )


def _render_log_copy_button(logs: list, *, title: str, key: str) -> None:
    if not logs:
        return
    _render_clipboard_button(
        "복사",
        ui_formatters.format_activity_log_markdown(
            logs,
            title=title,
            limit=_current_copy_log_limit(),
        ),
        key=key,
    )


def _render_review_package_copy_button() -> None:
    """Copy the full review context that the user usually pastes back for critique."""

    ir = st.session_state.get("intel_result") or {}
    intel_logs = list(st.session_state.get("intel_log", []) or [])
    draft_logs = list(st.session_state.get("swarm_log", []) or [])
    scripts = list(st.session_state.get("review_scripts", []) or [])
    gallery_id = (
        st.session_state.get("intel_gallery_id")
        or st.session_state.get("target_gallery_id")
        or ""
    )
    try:
        database.init_db()
        ai_post_comments = database.get_ai_post_comments(str(gallery_id), limit=120) if gallery_id else []
    except Exception:
        ai_post_comments = []
    if not (ir or intel_logs or draft_logs or scripts or ai_post_comments):
        return

    sentiment = ir.get("sentiment", "알 수 없음") if ir else "알 수 없음"
    st.markdown(
        '<div class="stack-package-actions">'
        '  <span>검토 패키지</span>'
        '  <em>필요한 범위만 골라 복사합니다.</em>'
        '</div>',
        unsafe_allow_html=True,
    )
    if scripts:
        _render_clipboard_button(
            "원고만 복사",
            ui_formatters.format_scripts_markdown(scripts),
            key="review_scripts_md_copy",
        )
    rehearsal_runs = list(st.session_state.get("rehearsal_runs", []) or [])
    if rehearsal_runs:
        _render_clipboard_button(
            "리허설 전체 복사",
            rehearsal_flow.format_markdown(
                rehearsal_runs,
                gallery_id=str(gallery_id),
            ),
            key="rehearsal_runs_md_copy",
        )
    _render_clipboard_button(
        "운영 리포트 복사",
        observability.format_ops_markdown(
            state=st.session_state,
            scripts=scripts,
            logs=intel_logs + draft_logs,
            intel_result=ir,
            stability_markdown=stability.format_stability_markdown(
                stability.evaluate_stability(
                    st.session_state,
                    scripts=scripts,
                    logs=intel_logs + draft_logs,
                    intel_result=ir,
                    ai_comments=ai_post_comments,
                )
            ),
        ),
        key="ops_report_md_copy",
    )
    _render_clipboard_button(
        "전체 복사",
        ui_formatters.format_review_package_markdown(
            intel_result=ir,
            gallery_id=str(gallery_id),
            sentiment=sentiment,
            generation_guidance=_build_ai_generation_guidance(ir) if ir else "",
            intel_logs=intel_logs,
            draft_logs=draft_logs,
            scripts=scripts,
            ai_post_comments=ai_post_comments,
            log_limit=_current_copy_log_limit(),
        ),
        key="review_package_md_copy",
    )


def _ops_status_word(status: object) -> str:
    value = str(status or "").lower()
    if value in {"good", "ok"}:
        return "정상"
    if value in {"bad", "critical"}:
        return "정지"
    if value in {"warn", "warning"}:
        return "점검"
    if value in {"info", "running"}:
        return "진행"
    if value == "empty":
        return "대기"
    return "확인"


def _ops_status_class(status: object) -> str:
    value = str(status or "").lower()
    if value in {"good", "ok"}:
        return "is-good"
    if value in {"bad", "critical"}:
        return "is-bad"
    if value in {"warn", "warning"}:
        return "is-warn"
    if value in {"info", "running"}:
        return "is-info"
    return "is-idle"


def _ops_styles() -> str:
    return (
        "<style>"
        ".ops-card{margin:12px 0;border:1px solid #E2E8F0;border-radius:20px;"
        "background:linear-gradient(145deg,#fff 0%,#F8FAFF 100%);"
        "box-shadow:0 14px 30px -24px rgba(79,70,229,.45);padding:14px;}"
        ".ops-head{display:flex;align-items:center;justify-content:space-between;gap:10px;"
        "padding-bottom:10px;border-bottom:1px solid #E2E8F0;}"
        ".ops-head b{font-size:13px;color:#0F172A;letter-spacing:-.02em;}"
        ".ops-head span{font-size:10px;font-weight:900;color:#4F46E5;letter-spacing:.08em;}"
        ".ops-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:10px;}"
        ".ops-metric{border:1px solid #E2E8F0;border-radius:15px;background:#fff;padding:10px;"
        "min-width:0;box-shadow:0 8px 20px -18px rgba(79,70,229,.42);}"
        ".ops-metric span{display:block;font-size:10px;font-weight:850;color:#64748B;}"
        ".ops-metric b{display:block;margin-top:5px;font-size:15px;color:#0F172A;letter-spacing:-.03em;}"
        ".ops-metric em{display:block;margin-top:4px;font-style:normal;font-size:10px;color:#64748B;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}"
        ".ops-pill{border-radius:999px;padding:5px 9px;font-size:10px;font-weight:900;white-space:nowrap;}"
        ".ops-pill.is-good{color:#047857;background:#ECFDF5;border:1px solid #A7F3D0;}"
        ".ops-pill.is-warn{color:#B45309;background:#FFFBEB;border:1px solid #FDE68A;}"
        ".ops-pill.is-bad{color:#BE123C;background:#FFF1F2;border:1px solid #FDA4AF;}"
        ".ops-pill.is-info{color:#3730A3;background:#EEF2FF;border:1px solid #C7D2FE;}"
        ".ops-pill.is-idle{color:#475569;background:#F8FAFC;border:1px solid #E2E8F0;}"
        ".ops-list{margin-top:10px;display:grid;gap:7px;}"
        ".ops-row{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;align-items:start;"
        "font-size:12px;color:#334155;line-height:1.45;}"
        ".ops-dot{width:8px;height:8px;border-radius:999px;margin-top:5px;background:#6366F1;}"
        ".ops-row.is-good .ops-dot{background:#10B981;}"
        ".ops-row.is-warn .ops-dot{background:#F59E0B;}"
        ".ops-row.is-bad .ops-dot{background:#F43F5E;}"
        ".ops-row.is-info .ops-dot{background:#6366F1;}"
        ".ops-row small{display:block;color:#94A3B8;font-weight:750;}"
        ".ops-row p{margin:0;white-space:normal;overflow-wrap:anywhere;}"
        "</style>"
    )


def _collect_ops_logs() -> list:
    return list(st.session_state.get("intel_log", []) or []) + list(
        st.session_state.get("swarm_log", []) or []
    )


def _render_ops_summary_card() -> str:
    scripts = list(st.session_state.get("review_scripts", []) or [])
    gallery_id = (
        st.session_state.get("target_gallery_id")
        or st.session_state.get("intel_gallery_id")
        or st.session_state.get("run_gallery_id")
        or ""
    )
    target_count = int(
        st.session_state.get("swarm_wave_total")
        or st.session_state.get("swarm_wave_count")
        or st.session_state.get("run_target_count")
        or 0
    )
    draft = observability.summarize_drafts(
        scripts,
        gallery_id=str(gallery_id),
        target_count=target_count,
    )
    source = observability.source_snapshot_health(
        st.session_state.get("intel_result"),
        requested_pages=int(st.session_state.get("intel_pages", 0) or 0),
    )
    diagnostics = observability.classify_gemini_logs(_collect_ops_logs())
    stability_report = _evaluate_ops_stability()
    diag_status = stability_report.get("status") or (
        "good" if not diagnostics else diagnostics[0].get("severity", "warn")
    )
    cycles = list(st.session_state.get("run_cycles", []) or [])
    latest_cycle = cycles[-1] if cycles else {}
    latest_summary = latest_cycle.get("summary", {}) if isinstance(latest_cycle, dict) else {}
    top_reason = "대기"
    if st.session_state.get("_ops_last_stop_reason"):
        top_reason = str(st.session_state.get("_ops_last_stop_reason"))
    elif draft.get("failure_reasons"):
        top_reason = str(draft["failure_reasons"][0][0])
    elif latest_summary.get("failure_reasons"):
        top_reason = str(latest_summary["failure_reasons"][0][0])
    source_label = f"{source.get('raw_count', 0)}글/{source.get('comment_count', 0)}댓"
    ready_label = f"{draft.get('valid', 0)}/{draft.get('requested', 0)}"
    cycle_label = f"{len(cycles)}회"
    phase_label = str(stability_report.get("phase") or st.session_state.get("run_mode") or "idle")
    return (
        _ops_styles()
        + '<div class="ops-card">'
        + '<div class="ops-head"><b>운영 요약</b>'
        + f'<span class="ops-pill {_ops_status_class(diag_status)}">{_html.escape(_ops_status_word(diag_status))}</span></div>'
        + '<div class="ops-grid">'
        + f'<div class="ops-metric"><span>원고</span><b>{_html.escape(ready_label)}</b><em>{_html.escape(top_reason)}</em></div>'
        + f'<div class="ops-metric"><span>원본</span><b>{_html.escape(source_label)}</b><em>{_html.escape(str(source.get("note") or ""))}</em></div>'
        + f'<div class="ops-metric"><span>사이클</span><b>{_html.escape(cycle_label)}</b><em>{_html.escape(phase_label)}</em></div>'
        + "</div></div>"
    )


def _render_ops_diagnostics_panel() -> str:
    scripts = list(st.session_state.get("review_scripts", []) or [])
    gallery_id = st.session_state.get("target_gallery_id") or st.session_state.get("intel_gallery_id") or ""
    target_count = int(st.session_state.get("swarm_wave_total") or st.session_state.get("swarm_wave_count") or 0)
    draft = observability.summarize_drafts(
        scripts,
        gallery_id=str(gallery_id),
        target_count=target_count,
    )
    source = observability.source_snapshot_health(
        st.session_state.get("intel_result"),
        requested_pages=int(st.session_state.get("intel_pages", 0) or 0),
    )
    diagnostics = observability.classify_gemini_logs(_collect_ops_logs())
    stability_report = _evaluate_ops_stability()
    events = list(st.session_state.get("run_timeline", []) or [])[-6:]
    rows: list[str] = []
    findings = list(stability_report.get("findings") or [])
    if findings:
        for item in findings[:3]:
            rows.append(
                f'<div class="ops-row {_ops_status_class(item.get("severity"))}"><i class="ops-dot"></i>'
                f'<p><b>{_html.escape(str(item.get("title") or ""))}</b>'
                f'<small>{_html.escape(str(item.get("action") or ""))}</small></p></div>'
            )
    if diagnostics:
        for item in diagnostics[:3]:
            rows.append(
                f'<div class="ops-row {_ops_status_class(item.get("severity"))}"><i class="ops-dot"></i>'
                f'<p><b>{_html.escape(item.get("title", ""))}</b>'
                f'<small>{_html.escape(item.get("action", ""))}</small></p></div>'
            )
    elif not findings:
        rows.append(
            '<div class="ops-row is-good"><i class="ops-dot"></i>'
            '<p><b>Gemini/API 진단 이상 없음</b><small>로그 기준으로 치명 오류는 보이지 않습니다.</small></p></div>'
        )
    feedback = stability_report.get("feedback") or {}
    if int(feedback.get("total") or 0):
        rows.append(
            '<div class="ops-row is-info"><i class="ops-dot"></i>'
            f'<p><b>댓글 감시 {int(feedback.get("total") or 0)}개</b>'
            f'<small>경고 {int(feedback.get("flagged") or 0)}개 · 발행 ID 기준으로 묶음</small></p></div>'
        )
    for event in events[-3:]:
        rows.append(
            f'<div class="ops-row {_ops_status_class(event.get("status"))}"><i class="ops-dot"></i>'
            f'<p><b>{_html.escape(str(event.get("title") or ""))}</b>'
            f'<small>{_html.escape(str(event.get("time") or ""))} · {_html.escape(str(event.get("detail") or ""))}</small></p></div>'
        )
    return (
        _ops_styles()
        + '<div class="ops-card">'
        + '<div class="ops-head"><b>진단 / 품질</b>'
        + f'<span>원고 {int(draft.get("valid", 0))}/{int(draft.get("requested", 0))} · 원본 {int(source.get("raw_count", 0))}</span></div>'
        + '<div class="ops-list">'
        + "".join(rows)
        + "</div></div>"
    )


def _render_studio_intel(ir: dict, *, gallery_id: str, sentiment: str) -> str:
    stats = ir.get("stats", {}) or {}
    summary = _studio_clip(ir.get("ai_analysis") or ir.get("summary") or "분석 결과가 준비됐습니다.", 900)
    guidance = _studio_clip(_build_ai_generation_guidance(ir) or "", 520)
    direction = _studio_clip(ir.get("summary") or "", 180)
    hot_topics = _studio_chip_row(ir.get("hot_topics", []), limit=4)
    keywords = _studio_chip_row(ir.get("top_keywords", []), limit=8)
    gallery_label = _gallery_display_name(gallery_id)
    gallery_heading_html = f'  <h3>{_html.escape(gallery_label)}</h3>' if gallery_label else ""
    guidance_html = (
        '<div class="studio-guidance-box">'
        '<span>작문 지시</span>'
        f'<p>{_html.escape(guidance)}</p>'
        '</div>'
        if guidance else ""
    )
    return (
        '<div class="studio-intel-card">'
        '  <div class="studio-card-head">'
        f'    <span>분위기</span><b>{_html.escape(gallery_label or "게시판")}</b>'
        '  </div>'
        f'  <div class="studio-intel-mood">{_html.escape(str(sentiment))}</div>'
        f'  <p>{_html.escape(summary)}</p>'
        f'  {guidance_html}'
        f'  <div class="studio-chip-row is-hot">{hot_topics}</div>'
        f'  <div class="studio-chip-row">{keywords}</div>'
        f'  <div class="studio-intel-foot">'
        f'    <span>제목 {stats.get("titles_count", 0)}개</span>'
        f'    <span>댓글 {stats.get("comments_count", 0)}개</span>'
        f'    <span>키워드 {stats.get("keywords_found", 0)}개</span>'
        f'  </div>'
        f'  <small>{_html.escape(direction)}</small>'
        '</div>'
    )


def _render_source_post_collection(raw_posts: list[dict], *, ai_nos: set[str] | None = None, limit: int = 90) -> str:
    """Render source post snapshots as readable title/body/comment cards."""

    posts = [post for post in list(raw_posts or []) if isinstance(post, dict)]
    if not posts:
        return '<div class="source-collection-empty">원본 글 모음이 아직 없습니다.</div>'

    cards: list[str] = []
    for idx, post in enumerate(posts[:limit], 1):
        post_no = str(post.get("no") or post.get("post_no") or "").strip()
        page = post.get("page") or "?"
        title = str(post.get("title") or post.get("source_title") or "(제목 없음)").strip()
        content = " ".join(str(post.get("content") or "").split()) or "(본문 미수집)"
        comments = [
            " ".join(str(item or "").split())
            for item in list(post.get("comments") or [])[:5]
            if str(item or "").strip()
        ]
        comment_html = (
            "".join(f"<li>{_html.escape(comment)}</li>" for comment in comments)
            if comments
            else '<li class="is-empty">댓글 미수집 또는 없음</li>'
        )
        ai_badge = '<b class="is-ai">AI 기록</b>' if ai_nos and post_no in ai_nos else ""
        cards.append(
            '<article class="source-post-card">'
            f'  <header><span>{idx:02d}</span><em>p{_html.escape(str(page))} · #{_html.escape(post_no or "?")}</em>{ai_badge}</header>'
            f'  <h4>{_html.escape(title)}</h4>'
            f'  <p>{_html.escape(content[:420] + ("…" if len(content) > 420 else ""))}</p>'
            f'  <ul>{comment_html}</ul>'
            '</article>'
        )

    return (
        '<div class="source-collection">'
        f'  <div class="source-collection-head"><b>원본 글 모음</b><span>{min(len(posts), limit)} / {len(posts)}개</span></div>'
        '  <div class="source-post-grid">'
        + "".join(cards)
        + '  </div>'
        '</div>'
    )


def _render_studio_preview(*, title: str, content: str, wave_label: str) -> str:
    return (
        '<div class="studio-preview-card">'
        f'  <span>{_html.escape(wave_label)}</span>'
        f'  <h3>{_html.escape(title or "제목 없음")}</h3>'
        f'  <p>{_html.escape(content or "본문 없음")}</p>'
        '</div>'
    )


def _render_studio_empty_preview() -> str:
    return (
        '<div class="studio-preview-card is-empty">'
        '  <span>대기</span>'
        '  <h3>아직 만든 원고가 없습니다.</h3>'
        '  <p>주제를 입력하고 원고를 만들면 여기에서 바로 확인합니다.</p>'
        '</div>'
    )


def _render_draft_comment_list(target_comments: list[dict] | tuple) -> str:
    """Render comment drafts in the review card's dedicated comment column."""
    comments = []
    for item in target_comments or []:
        if not isinstance(item, dict):
            continue
        comment = str(item.get("comment") or "").strip()
        if not comment:
            continue
        post_no = str(item.get("post_no") or "").strip()
        target = f"#{post_no}" if post_no else "대상 글"
        rehearsal_badge = (
            '<em class="comment-rehearsal-badge">리허설</em>'
            if item.get("simulation_only") or item.get("is_ai_post")
            else ""
        )
        comments.append(
            '<li>'
            f'<div class="draft-comment-target"><b>{_html.escape(target)}</b>{rehearsal_badge}</div>'
            f'<span>{_html.escape(comment)}</span>'
            '</li>'
        )
    if not comments:
        return (
            '<section class="draft-comment-list is-empty">'
            '  <header><span>댓글 초안</span><b>0개</b></header>'
            '  <p class="draft-comment-empty">작성할 댓글 없음</p>'
            '</section>'
        )
    return (
        '<section class="draft-comment-list">'
        f'  <header><span>댓글 초안</span><b>{len(comments)}개</b></header>'
        f'  <ul>{"".join(comments)}</ul>'
        '</section>'
    )


def _render_publish_draft_stack(
    scripts: list[dict] | tuple,
    *,
    current_wave: int = 0,
    height_px: int = 560,
) -> str:
    """Render all generated drafts as a tall publish-stage review stack."""

    valid = [item for item in (scripts or []) if not item.get("_failed")]
    if not valid:
        return (
            f'<div class="publish-draft-stack is-empty" style="height:{height_px}px">'
            '  <div class="publish-draft-empty">발행할 원고가 없습니다.</div>'
            '</div>'
        )

    cards: list[str] = []
    for idx, item in enumerate(valid, 1):
        wave = int(item.get("wave") or idx)
        title = str(item.get("title") or "(제목 없음)").strip()
        content = str(item.get("content") or "").strip()
        persona = str(item.get("persona_name") or item.get("tone") or "").strip()
        target_comments = item.get("target_comments") or []
        cls = "publish-draft-card"
        if current_wave and wave < current_wave:
            cls += " is-done"
        elif current_wave and wave == current_wave:
            cls += " is-current"
        meta = " · ".join(part for part in (persona, f"댓글 {len(target_comments)}") if part)
        cards.append(
            f'<article class="{cls}">'
            f'  <header><span>원고 {idx}</span><em>{_html.escape(meta)}</em></header>'
            f'  <h3>{_html.escape(title)}</h3>'
            f'  <p>{_html.escape(content)}</p>'
            f'  {_render_draft_comment_list(target_comments)}'
            '</article>'
        )

    return (
        f'<div class="publish-draft-stack" style="height:{height_px}px">'
        + "".join(cards)
        + '</div>'
    )


def _render_studio_stat(*, value: object, label: str, tone: str = "") -> str:
    safe_tone = _html.escape(tone, quote=True)
    return (
        f'<div class="studio-stat {safe_tone}">'
        f'  <b>{_html.escape(str(value))}</b>'
        f'  <span>{_html.escape(label)}</span>'
        f'</div>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# DB CSV 내보내기 — @st.cache_data 래퍼 (module level 필수)
# ttl=300: 5분 캐시 → 재렌더 시 재연산 없음 / 신선도 균형
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — INTEL 결과 렌더링 + 폴링
# 이 fragment만 0.5초마다 재실행 — 전체 페이지 flickering 없음
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment(run_every=_POLL_INTERVAL_SECONDS)
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
        for msg in worker_contracts.drain_queue(iq):
            msg_type = msg.get("type")
            if msg_type == worker_contracts.MSG_INTEL_RESULT:
                source = observability.source_snapshot_health(
                    msg.get("data") or {},
                    requested_pages=int(ss.get("intel_pages", 0) or 0),
                )
                observability.append_event(
                    ss,
                    kind="read_result",
                    title="board snapshot analyzed",
                    detail=(
                        f"{source.get('raw_count', 0)} posts, "
                        f"{source.get('comment_count', 0)} comments"
                    ),
                    status=source.get("status", "info"),
                    metrics=source,
                )
            if apply_intel_message(ss, msg):
                _intel_done = True
                observability.append_event(
                    ss,
                    kind="read_done",
                    title="board read worker done",
                    detail=f"logs={len(ss.get('intel_log', []) or [])}",
                    status="ok" if ss.get("intel_result") else "warn",
                )
                # 분석 성공 시 갤러리 히스토리 저장 (파일 기반, 비파괴적)
                if ss.intel_result:
                    _history_save(
                        ss.get("intel_gallery_id", ""),
                        ss.get("intel_type_label", "마이너 (mgallery)"),
                    )

    # ── 표시할 결과 결정 (live result > cache) ─────────────────────────
    _ir = ss.intel_result
    if _ir is None and not ss.get("intel_running"):
        _ck = intel_cache.cache_key(
            ss.get("intel_gallery_id", ""),
            ss.get("intel_type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL),
        )
        _cached = ss.intel_cache.get(_ck)
        if intel_cache.is_cache_fresh(_cached):
            _ir = _cached["result"]

    # ── 결과 렌더링 ─────────────────────────────────────────────────────
    if _ir:
        _sent_raw = _ir.get("sentiment", "알 수 없음")
        _intel_gid = ss.get("intel_gallery_id", "")
        _raw_posts_scan = _ir.get("raw_posts", [])
        try:
            _ai_nos_db: set[str] = database.get_ai_post_nos(_intel_gid) if _intel_gid else set()
        except Exception:
            _ai_nos_db = set()

        st.markdown(
            _render_studio_intel(_ir, gallery_id=_intel_gid, sentiment=_sent_raw),
            unsafe_allow_html=True,
        )

        if ss.get("_intel_raw_open"):
            st.markdown('<div class="raw-data-panel-marker"></div>', unsafe_allow_html=True)
            st.markdown(
                _render_source_post_collection(_raw_posts_scan, ai_nos=_ai_nos_db),
                unsafe_allow_html=True,
            )

    elif ss.get("intel_running"):
        render_activity_panel_component(
            ss.intel_log,
            title="게시판 읽는 중",
            height_px=740,
            limit=260,
        )
    else:
        pass

    # ── 폴링 제어 ────────────────────────────────────────────────────────
    if _intel_done:
        st.rerun(scope="app")          # 전체 재실행 → 버튼 재활성화


# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — SWARM 모니터 (Preview + Terminal + Stats + STOP)
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment(run_every=_POLL_INTERVAL_SECONDS)
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
        for msg in worker_contracts.drain_queue(sq):
            if apply_swarm_message(ss, msg):
                _done_received = True

    # ── Status Strip ────────────────────────────────────────────────────
    _wave_disp = f"{ss.swarm_wave_current}/{ss.swarm_wave_total}" if ss.swarm_wave_total else "—"
    sc1, sc2, sc3, sc4 = st.columns([1, 1, 1, 1.1], gap="small")
    with sc1:
        st.markdown(_render_studio_stat(value=ss.posts_success, label="완료", tone="is-ok"), unsafe_allow_html=True)
    with sc2:
        st.markdown(_render_studio_stat(value=ss.posts_failed, label="실패", tone="is-error"), unsafe_allow_html=True)
    with sc3:
        st.markdown(_render_studio_stat(value=_wave_disp, label="진행", tone="is-wave"), unsafe_allow_html=True)
    with sc4:
        if st.button("상태 초기화", key="reset_stats_btn", use_container_width=True):
            reset_monitor_stats(ss)
            st.rerun(scope="app")

    # ── Preview + Terminal ───────────────────────────────────────────────
    publish_monitor_height = 720
    col_preview = st.container()

    with col_preview:
        st.markdown('<div class="studio-panel-label">생성된 원고</div>', unsafe_allow_html=True)
        st.markdown(
            _render_publish_draft_stack(
                ss.get("review_scripts", []) or [],
                current_wave=int(ss.get("swarm_wave_current", 0) or 0),
                height_px=publish_monitor_height,
            ),
            unsafe_allow_html=True,
        )

    if False:
        render_activity_panel_component(
            ss.swarm_log,
            title="발행 흐름",
            height_px=publish_monitor_height,
            limit=100,
        )

    # ── 테스트 모드 사이클 요약 ─────────────────────────────────────────
    if ss.get("wave_test_mode") and ss.get("test_summaries"):
        with st.expander("리허설 요약", expanded=False):
            st.text_area(
                "리허설 요약",
                value="\n".join(str(summary) for summary in ss.get("test_summaries", [])),
                height=180,
                key="test_summaries_text_area",
                label_visibility="collapsed",
            )
            if st.button("요약 초기화", key="clear_test_summaries", use_container_width=True):
                ss["test_summaries"] = []
                ss["_test_log_path"] = None
                st.rerun(scope="app")

    # ── 폴링 제어 ────────────────────────────────────────────────────────
    if _done_received:
        # 무한 모드: 포스팅 완료 후 다음 배치 자동 시작
        stability_report = _evaluate_ops_stability()
        stopped = _stop_infinite_for_stability(ss, stability_report, prefix="[PUBLISH]")
        if ss.get("swarm_infinite") and ss.get("_batch_gen_config") and not stopped:
            _start_next_batch(ss)
        st.rerun(scope="app")          # 전체 재실행 → 버튼 재활성화


# ══════════════════════════════════════════════════════════════════════════════
# @st.fragment — 배치 대본 생성 진행 모니터
# ══════════════════════════════════════════════════════════════════════════════
@st.fragment(run_every=_POLL_INTERVAL_SECONDS)
def _publish_log_fragment(*, height_px: int = 820) -> None:
    """Drain publish-worker events and render them in the right log column."""

    ss = st.session_state
    _done_received = False
    if ss.get("swarm_running") and ss.get("swarm_queue") is not None:
        sq: queue.Queue = ss.swarm_queue
        for msg in worker_contracts.drain_queue(sq):
            if apply_swarm_message(ss, msg):
                _done_received = True

    _cur = int(ss.get("swarm_wave_current", 0) or 0)
    _total = int(ss.get("swarm_wave_total", 0) or 0)
    if _total:
        st.markdown(
            render_stable_progress(_cur / _total, label=f"{_cur}/{_total}"),
            unsafe_allow_html=True,
        )

    logs = list(ss.get("swarm_log", []) or [])
    if ss.get("swarm_infinite"):
        logs = ["[∞] 무한모드 실행 중 — 현재 작업이 끝나면 다음 묶음으로 이어집니다."] + logs
    st.markdown(_render_ops_diagnostics_panel(), unsafe_allow_html=True)
    render_activity_panel_component(
        logs,
        title="발행 중",
        height_px=height_px,
        limit=_current_live_log_limit(),
    )

    if _done_received:
        observability.append_event(
            ss,
            kind="publish_done",
            title="publish worker done",
            detail=(
                f"success={ss.get('posts_success', 0)} "
                f"failed={ss.get('posts_failed', 0)}"
            ),
            status="ok" if int(ss.get("posts_failed", 0) or 0) == 0 else "warn",
            metrics={
                "success": ss.get("posts_success", 0),
                "failed": ss.get("posts_failed", 0),
            },
        )
        stability_report = _evaluate_ops_stability()
        stopped = _stop_infinite_for_stability(ss, stability_report, prefix="[PUBLISH]")
        if ss.get("swarm_infinite") and ss.get("_batch_gen_config") and not stopped:
            _start_next_batch(ss)
        st.rerun(scope="app")


@st.fragment(run_every=_POLL_INTERVAL_SECONDS)
def _batch_gen_fragment() -> None:
    """대본 일괄 생성 진행 상황을 보여주는 fragment.

    • batch_generating=True 동안 batch_gen_queue 드레인 → session_state 갱신
    • batch_done 수신 시 review_ready=True 설정 → scope='app' 재실행
    """
    ss = st.session_state

    _done = False
    if ss.get("batch_generating") and ss.get("batch_gen_queue") is not None:
        bq: queue.Queue = ss.batch_gen_queue
        for msg in worker_contracts.drain_queue(bq):
            if apply_batch_message(ss, msg):
                fatal_error = str(msg.get("fatal_error") or "").strip()
                if fatal_error:
                    ss["_infinite_refill_scripts"] = []
                    ss["_infinite_refill_round"] = 0
                    if ss.get("_batch_gen_config"):
                        ss["_batch_gen_config"]["infinite"] = False
                        ss["_batch_gen_config"]["wave_test_mode"] = False
                        ss["_batch_gen_config"]["rehearsal"] = False
                    try:
                        ss.swarm_infinite = False
                        ss.wave_test_mode = False
                    except Exception:
                        pass
                    ss.review_ready = False
                    ss.swarm_log.append(
                        f"[BATCH] Fatal worker error; infinite mode stopped: {fatal_error}"
                    )
                    observability.append_event(
                        ss,
                        kind="worker_fatal",
                        title="batch worker fatal error",
                        detail=fatal_error,
                        status="critical",
                    )
                    _done = True
                    continue
                if ss.get("wave_test_mode"):
                    result = _handle_rehearsal_batch_done(ss, msg)
                    if result == "next":
                        continue
                elif ss.get("swarm_infinite"):
                    result = _handle_infinite_batch_done(ss, msg["scripts"])
                    if result == "refilling":
                        continue
                else:
                    cfg = ss.get("_batch_gen_config", {}) or {}
                    observability.record_cycle(
                        ss,
                        cycle=int(getattr(ss, "_batch_cycle_count", 1) or 1),
                        mode="draft",
                        scripts=msg.get("scripts") or [],
                        target_count=int(cfg.get("wave_count", 0) or 0),
                        gallery_id=str(cfg.get("gallery_id") or ""),
                        status="complete",
                    )
                    ss.review_ready  = bool(msg["scripts"])
                _done = True

    # 진행 상태는 상단 실행 카드에서 보여주고, 이 fragment는 큐 드레인만 담당한다.
    _cur = ss.get("swarm_wave_current", 0)
    _total = ss.get("swarm_wave_total", 0)
    _ratio = (_cur / _total) if _total else 0
    if _total > 0:
        st.markdown(
            render_stable_progress(_ratio, label=f"{_cur}/{_total}"),
            unsafe_allow_html=True,
        )
    st.markdown(_render_ops_diagnostics_panel(), unsafe_allow_html=True)
    render_activity_panel_component(
        ss.swarm_log,
        title="초안 작성 중",
        height_px=620,
        limit=_current_live_log_limit(),
    )

    # 폴링 제어
    if _done:
        st.rerun(scope="app")


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
            '<div class="pd-empty">생성된 원고가 없습니다.<br>왼쪽에서 원고 만들기를 다시 눌러주세요.</div>',
            unsafe_allow_html=True,
        )
        return

    valid   = [s for s in scripts if not s.get("_failed")]
    failed  = [s for s in scripts if s.get("_failed")]
    _total  = len(scripts)
    _ok     = len(valid)

    st.markdown(
        f'<div class="section-hdr">검토할 원고 — {_ok} / {_total}개 준비됨</div>',
        unsafe_allow_html=True,
    )

    # 원고 목록은 Streamlit 컬럼이 아니라 고정 그리드로 렌더링해 가로로 늘어지지 않게 한다.
    review_tiles: list[str] = []
    for idx, s in enumerate(valid):
        wave        = s["wave"]
        title       = s.get("title", "")
        content     = s.get("content", "")
        persona     = s.get("persona_name", "")
        tone_key    = s.get("tone", "")
        target_comments = s.get("target_comments") or []

        row_cls = "review-tile"
        safe_title = _html.escape(title or "(제목 없음)")
        safe_content = _html.escape(content or "본문 없음")
        safe_meta = _html.escape(" · ".join(part for part in (persona, tone_key) if part))

        body_html = (
            '<div class="review-tile-layout">'
            '  <div class="review-tile-copy">'
            f'    <h3>{safe_title}</h3>'
            f'    <p class="review-tile-body">{safe_content}</p>'
            '  </div>'
            f'  <div class="review-tile-comments">{_render_draft_comment_list(target_comments)}</div>'
            '</div>'
        )

        review_tiles.append(
            f'<article class="{row_cls}">'
            f'  <header><span>원고 {wave}</span><em>{safe_meta}</em></header>'
            f'  {body_html}'
            f'</article>'
        )

    st.markdown(
        '<div class="review-tile-grid">' + "".join(review_tiles) + '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)

    if failed:
        st.markdown(
            f'<div class="failed-review-title">생성 실패 원고 <b>{len(failed)}</b>'
            '<span>마지막 후보를 확인한 뒤 수동으로 포함할 수 있습니다.</span></div>',
            unsafe_allow_html=True,
        )
        for script_index, script in enumerate(scripts):
            if not script.get("_failed"):
                continue
            rejected_title = str(script.get("_rejected_title") or "").strip()
            rejected_content = str(script.get("_rejected_content") or "").strip()
            rejected_comments = script.get("_rejected_comments") or []
            reason = str(script.get("_failure_reason") or "검증을 통과하지 못했습니다.").strip()
            failure_stage = str(script.get("_failure_stage") or "").strip()
            safety_blocked = failure_stage == "safety_filter" or reason == "안전 필터"
            wave = int(script.get("wave") or script_index + 1)
            persona = _html.escape(
                str(script.get("persona_name") or script.get("tone") or "")
            )
            st.markdown(
                '<article class="failed-review-tile">'
                f'<header><span>원고 {wave}</span><em>{persona}</em></header>'
                f'<strong>{_html.escape(rejected_title or "복구 가능한 후보 없음")}</strong>'
                f'<p>{_html.escape(rejected_content or reason)}</p>'
                f'<small>{_html.escape(reason)}</small>'
                f'{_render_draft_comment_list(rejected_comments)}'
                '</article>',
                unsafe_allow_html=True,
            )
            if st.button(
                (
                    "안전 필터 후보는 검토 전용"
                    if safety_blocked
                    else "이 후보를 발행 목록에 포함"
                ),
                key=f"restore_failed_script_{script_index}",
                use_container_width=False,
                disabled=safety_blocked or not (rejected_title and rejected_content),
            ):
                restored = dict(script)
                restored.update(
                    {
                        "title": rejected_title,
                        "content": rejected_content,
                        "target_comments": list(rejected_comments),
                        "_failed": False,
                        "_manual_override": True,
                    }
                )
                updated = list(scripts)
                updated[script_index] = restored
                ss.review_scripts = updated
                ss.review_ready = True
                st.rerun(scope="app")

    if not valid:
        st.error("❌ 발행 가능한 원고가 없습니다. 폐기 후 다시 생성하세요.")
        if st.button("폐기하고 다시 만들기", key="review_discard_only_btn", use_container_width=True):
            ss.review_ready   = False
            ss.review_scripts = []
            st.rerun(scope="app")
        return

    st.markdown('<div class="review-action-hint">발행 시작과 폐기는 왼쪽 실행 패널에서 바로 처리합니다.</div>', unsafe_allow_html=True)


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
# TOP STATUS — keep the chrome quiet so the composer stays first.
# ══════════════════════════════════════════════
_api_status_label = "API 연결됨" if _GEMINI_API_KEY else "API 키 필요"
_api_status_class = "is-ready" if _GEMINI_API_KEY else "is-missing"

# ══════════════════════════════════════════════════════════════════════════════
# MAIN COMPOSER — primary work surface
# ══════════════════════════════════════════════════════════════════════════════
_intel_is_running = st.session_state.get("intel_running", False)
_is_running       = st.session_state.get("swarm_running", False)
_is_generating    = st.session_state.get("batch_generating", False)
_is_reviewing     = st.session_state.get("review_ready", False)
_any_busy         = _is_running or _is_generating or _is_reviewing

fire_clicked = False
_intel_fire = False

_hist_entries = _history_load()
_ltc_restore = intel_cache.load_last_topic_cache()


def _infer_gallery_from_logs(logs: list) -> str:
    """Recover the gallery id from existing Intel logs when widget state was reset."""
    for line in logs or []:
        text = str(line)
        if "gallery_id=" in text:
            return text.split("gallery_id=", 1)[1].split()[0].strip("),.;")
        if "트렌드 수집" in text or "AJAX" in text:
            match = re.search(r"\[([A-Za-z][A-Za-z0-9_]{1,48})\]", text)
            if match:
                return match.group(1)
    return ""


def _ensure_workbench_context() -> None:
    """Keep the board identity attached to the current briefing across reruns."""
    target_gid = str(st.session_state.get("target_gallery_id", "") or "").strip()
    intel_gid = str(st.session_state.get("intel_gallery_id", "") or "").strip()
    has_current_brief = bool(st.session_state.get("intel_result"))
    log_gid = _infer_gallery_from_logs(st.session_state.get("intel_log", [])) if has_current_brief else ""
    gallery_id = target_gid or intel_gid or log_gid

    target_type = st.session_state.get("target_type_label")
    intel_type = st.session_state.get("intel_type_label")
    known_type = _known_type_for_gallery(gallery_id)
    type_label = ui_options.normalize_gallery_type_label(
        known_type or target_type or intel_type or ui_options.DEFAULT_GALLERY_TYPE_LABEL
    )

    if gallery_id:
        if not target_gid:
            st.session_state["target_gallery_id"] = gallery_id
        if not intel_gid:
            st.session_state["intel_gallery_id"] = gallery_id
        if known_type and st.session_state.get("target_type_label") == ui_options.DEFAULT_GALLERY_TYPE_LABEL:
            st.session_state["target_type_label"] = known_type
        if known_type and st.session_state.get("intel_type_label") == ui_options.DEFAULT_GALLERY_TYPE_LABEL:
            st.session_state["intel_type_label"] = known_type
    st.session_state.setdefault("target_type_label", type_label)
    st.session_state.setdefault("intel_type_label", type_label)
    if not st.session_state.get("target_type_label"):
        st.session_state["target_type_label"] = type_label
    if not st.session_state.get("intel_type_label"):
        st.session_state["intel_type_label"] = type_label


def _known_type_for_gallery(gallery_id: str) -> str | None:
    if not gallery_id:
        return None
    for entry in _hist_entries:
        if entry.get("gallery_id") == gallery_id:
            return ui_options.normalize_gallery_type_label(
                entry.get("type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
            )
    if _ltc_restore and _ltc_restore.get("gallery_id") == gallery_id:
        return ui_options.normalize_gallery_type_label(
            _ltc_restore.get("type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
        )
    return None


def _default_gallery_pair() -> tuple[str, str]:
    if _hist_entries:
        entry = _hist_entries[0]
        gallery_id = str(entry.get("gallery_id", "") or "").strip()
        type_label = ui_options.normalize_gallery_type_label(
            entry.get("type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
        )
        if gallery_id:
            return gallery_id, type_label
    if _ltc_restore:
        gallery_id = str(_ltc_restore.get("gallery_id", "") or "").strip()
        type_label = ui_options.normalize_gallery_type_label(
            _ltc_restore.get("type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
        )
        if gallery_id:
            return gallery_id, type_label
    return "", ui_options.DEFAULT_GALLERY_TYPE_LABEL


def _reset_stale_autofill_defaults() -> None:
    """Undo previous over-eager history autofill when the app is otherwise idle."""
    if st.session_state.get("_defaults_reset_history_type_fix"):
        return
    has_work = bool(
        st.session_state.get("intel_result")
        or st.session_state.get("review_scripts")
        or st.session_state.get("batch_generating")
        or st.session_state.get("swarm_running")
        or st.session_state.get("review_ready")
    )
    if not has_work:
        default_gallery_id, default_type_label = _default_gallery_pair()
        st.session_state["target_gallery_id"] = default_gallery_id
        st.session_state["intel_gallery_id"] = default_gallery_id
        st.session_state["target_type_label"] = default_type_label
        st.session_state["intel_type_label"] = default_type_label
        st.session_state["intel_pages"] = 3
        st.session_state["swarm_wave_count"] = 3
        st.session_state["swarm_topic_input"] = ""
        st.session_state["intel_log"] = []
        st.session_state["swarm_log"] = []
    st.session_state["_defaults_reset_history_type_fix"] = True


def _apply_quick_pick(kind: str, payload: dict) -> None:
    """Apply a history shortcut before Streamlit instantiates keyed widgets again."""
    if kind == "history":
        gallery_id = payload.get("gallery_id", "")
        type_label = ui_options.normalize_gallery_type_label(
            payload.get("type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
        )
        st.session_state["target_gallery_id"] = gallery_id
        st.session_state["target_type_label"] = type_label
        st.session_state["intel_gallery_id"] = gallery_id
        st.session_state["intel_type_label"] = type_label
        return

    gallery_id = payload.get("gallery_id", "")
    type_label = ui_options.normalize_gallery_type_label(
        payload.get("type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
    )
    if "result" in payload:
        st.session_state["intel_result"] = payload["result"]
    st.session_state["target_gallery_id"] = gallery_id
    st.session_state["target_type_label"] = type_label
    st.session_state["intel_gallery_id"] = gallery_id
    st.session_state["intel_type_label"] = type_label


def _toggle_recent_manage() -> None:
    st.session_state["_recent_manage_open"] = not st.session_state.get("_recent_manage_open", False)


def _toggle_advanced_manage() -> None:
    st.session_state["_advanced_manage_open"] = not st.session_state.get("_advanced_manage_open", False)


def _render_recent_manage_panel() -> None:
    is_open = bool(st.session_state.get("_recent_manage_open", False))
    st.button(
        "최근/관리 닫기" if is_open else "최근/관리 열기",
        key="recent_manage_toggle_btn",
        use_container_width=True,
        on_click=_toggle_recent_manage,
    )
    if not is_open:
        return

    st.markdown('<div class="utility-panel-marker"></div>', unsafe_allow_html=True)

    _quick_items = []
    for _he in _hist_entries[:4]:
        _quick_items.append(("history", _he["gallery_id"], _he))
    if _ltc_restore and not _intel_is_running:
        _quick_items.append(("restore", "이전 분석", _ltc_restore))

    if _quick_items:
        _hcols = st.columns(2, gap="small")
        for _hi, (_kind, _label, _payload) in enumerate(_quick_items):
            with _hcols[_hi % len(_hcols)]:
                st.button(
                    _label,
                    key=f"quick_pick_{_kind}_{_hi}",
                    use_container_width=True,
                    on_click=_apply_quick_pick,
                    args=(_kind, _payload),
                )
    else:
        st.markdown('<div class="utility-empty">아직 최근 기록이 없습니다.</div>', unsafe_allow_html=True)

    adv_open = bool(st.session_state.get("_advanced_manage_open", False))
    st.button(
        "고급 닫기" if adv_open else "고급",
        key="advanced_manage_toggle_btn",
        use_container_width=True,
        on_click=_toggle_advanced_manage,
    )

    if adv_open:
        _advanced_interval_unit = "초" if st.session_state.get("wave_test_mode", False) else "분"
        st.toggle(
            "브라우저 숨김",
            key="target_headless",
            help="켜짐: 백그라운드 실행 / 꺼짐: 디버깅용 화면 표시",
        )
        st.number_input(
            "댓글 감시 글 수",
            min_value=0,
            max_value=30,
            step=1,
            key="ai_comment_watch_limit",
            help="발행 후 최근 AI 작성글 몇 개의 댓글을 재확인할지 정합니다.",
        )
        gemini_wait_cols = st.columns([1, 1], gap="small")
        with gemini_wait_cols[0]:
            st.number_input(
                "Gemini 간격(초)",
                min_value=0.0,
                max_value=30.0,
                step=0.5,
                key="gemini_call_min_interval_sec",
                help="Gemini API 호출 사이에 최소로 띄울 시간입니다. 429가 보이면 3~5초로 올려보세요.",
            )
        with gemini_wait_cols[1]:
            st.number_input(
                "Gemini 지터(초)",
                min_value=0.0,
                max_value=10.0,
                step=0.25,
                key="gemini_call_jitter_sec",
                help="동시에 몰리는 호출을 흩어놓기 위한 추가 랜덤 대기입니다.",
            )
        adv_wait_cols = st.columns([1, 1], gap="small")
        with adv_wait_cols[0]:
            st.number_input(
                f"랜덤 최소 ({_advanced_interval_unit})",
                min_value=0,
                max_value=60,
                step=1,
                key="wave_interval_min",
                help="발행 간격 값이 없을 때만 쓰는 백업 랜덤 대기입니다.",
            )
        with adv_wait_cols[1]:
            st.number_input(
                f"랜덤 최대 ({_advanced_interval_unit})",
                min_value=0,
                max_value=60,
                step=1,
                key="wave_interval_max",
                help="발행 간격 값이 없을 때만 쓰는 백업 랜덤 대기입니다.",
            )

        st.markdown('<div class="utility-section-title">관리</div>', unsafe_allow_html=True)
        _admin_cols = st.columns(2, gap="small")
        with _admin_cols[0]:
            if st.button("업데이트", key="studio_update_btn", use_container_width=True,
                         help="git pull + 프롬프트 캐시 초기화. 코드·프롬프트 변경사항을 즉시 반영합니다."):
                pm._read_file.cache_clear()
                pm.load_json.cache_clear()
                _r = subprocess.run(
                    ["git", "pull"],
                    capture_output=True, text=True,
                    cwd=str(Path(__file__).parent),
                )
                _out = (_r.stdout or _r.stderr or "").strip()
                st.toast(
                    f"프롬프트 캐시 초기화 완료\n{_out or 'Git pull 완료'}",
                    icon="✅" if _r.returncode == 0 else "❌",
                )
                st.rerun()
        with _admin_cols[1]:
            if not st.session_state.get("_db_reset_confirm", False):
                if st.button(
                    "DB 초기화",
                    use_container_width=True,
                    key="db_reset_btn",
                    help="이전 테스트 찌꺼기 게시글·댓글 전체 삭제. Context Poisoning 방지용.",
                ):
                    st.session_state["_db_reset_confirm"] = True
                    st.rerun()
            else:
                st.warning("게시글·댓글 DB를 전체 삭제합니다. 되돌릴 수 없습니다.")
                _drc1, _drc2 = st.columns(2)
                with _drc1:
                    if st.button("삭제 확인", use_container_width=True,
                                 type="primary", key="db_reset_confirm_btn"):
                        try:
                            database.init_db()
                            _deleted = database.truncate_posts()
                            st.session_state["_db_reset_confirm"] = False
                            st.toast(f"DB 초기화 완료 — {_deleted}건 삭제", icon="✅")
                            st.rerun()
                        except Exception as _dbe:
                            st.error(f"삭제 실패: {str(_dbe)[:120]}")
                            st.session_state["_db_reset_confirm"] = False
                with _drc2:
                    if st.button("취소", use_container_width=True, key="db_reset_cancel_btn"):
                        st.session_state["_db_reset_confirm"] = False
                        st.rerun()


_reset_stale_autofill_defaults()
_ensure_workbench_context()
st.session_state["target_tone_label"] = ui_options.DEFAULT_TONE_LABEL
st.session_state["target_length"] = ui_options.DEFAULT_LENGTH_LABEL
_has_brief = bool(st.session_state.get("intel_result"))
_has_drafts = bool(st.session_state.get("review_scripts"))

_workbench_gallery_id = (
    st.session_state.get("target_gallery_id", "")
    or st.session_state.get("intel_gallery_id", "")
).strip()
_workbench_topic_val = st.session_state.get("swarm_topic_input", "").strip()
_workbench_intel_disabled = not has_any_key or not _workbench_gallery_id or _intel_is_running
_workbench_fire_disabled = (
    not has_any_key
    or not _workbench_gallery_id
    or not _workbench_topic_val
    or _any_busy
)
if _is_generating:
    _workbench_draft_label = "작성 중"
elif _is_reviewing:
    _workbench_draft_label = "검토 대기"
elif _is_running:
    _workbench_draft_label = "발행 중"
else:
    if st.session_state.get("wave_test_mode", False):
        _workbench_draft_label = "리허설 시작"
    elif st.session_state.get("swarm_infinite", False):
        _workbench_draft_label = "시작"
    else:
        _workbench_draft_label = "원고 만들기"

if not has_any_key:
    _workbench_state_text = "API 키 필요"
    _workbench_state_cls = "is-blocked"
elif not _workbench_gallery_id:
    _workbench_state_text = "게시판 필요"
    _workbench_state_cls = "is-blocked"
elif not _workbench_topic_val:
    _workbench_state_text = "주제 대기"
    _workbench_state_cls = "is-waiting"
else:
    _workbench_state_text = "실행 준비"
    _workbench_state_cls = "is-ready"

_intel_logs = list(st.session_state.get("intel_log", []) or [])
_swarm_logs = list(st.session_state.get("swarm_log", []) or [])
_live_logs: list = _intel_logs + _swarm_logs
_live_title = "누적 로그"
if _intel_is_running:
    _live_logs = _intel_logs
    _live_title = "게시판 읽는 중"
elif _is_generating:
    _live_logs = _swarm_logs
    _live_title = "초안 작성 중"
elif _is_running:
    _live_logs = _swarm_logs
    _live_title = "발행 중"
elif _is_reviewing and _swarm_logs:
    _live_logs = _swarm_logs
    _live_title = "초안 작성 로그"
elif _has_brief and _intel_logs:
    _live_logs = _intel_logs
    _live_title = "게시판 읽기 로그"

_mode_headers = []
if st.session_state.get("swarm_infinite") and (_is_generating or _is_running):
    _mode_headers.append("[MODE] 무한 실행 — 현재 작업 뒤 다음 묶음으로 이어집니다.")
if st.session_state.get("wave_test_mode") and (_is_generating or _is_running):
    _mode_headers.append("[MODE] 리허설 — 실제 게시 없이 전체 순환을 점검합니다.")
if _mode_headers:
    _live_logs = _mode_headers + list(_live_logs)


def _rail_item(num: str, label: str, state: str) -> str:
    safe_state = _html.escape(state, quote=True)
    return (
        f'<div class="rail-item {safe_state}">'
        f'  <span>{_html.escape(num)}</span>'
        f'  <b>{_html.escape(label)}</b>'
        f'</div>'
    )


_read_state = "is-active" if _intel_is_running else ("is-done" if _has_brief else "is-ready")
_write_state = "is-active" if _is_generating else ("is-done" if _has_drafts else "is-ready")
_review_state = "is-active" if _is_reviewing else ("is-done" if _is_running else "is-ready")
_publish_state = "is-active" if _is_running else (
    "is-done" if st.session_state.get("posts_success", 0) else "is-ready"
)
if _is_running:
    _active_stage = "publish"
elif _is_generating or _is_reviewing or st.session_state.get("review_ready"):
    _active_stage = "review"
elif _intel_is_running:
    _active_stage = "intel"
elif _has_brief:
    _active_stage = "write"
else:
    _active_stage = "read"


def _stage_summary(num: str, label: str, value: str, state: str) -> str:
    safe_state = _html.escape(state, quote=True)
    return (
        f'<div class="stage-summary {safe_state}">'
        f'  <span>{_html.escape(num)}</span>'
        f'  <b>{_html.escape(label)}</b>'
        f'  <em>{_html.escape(value)}</em>'
        f'</div>'
    )


def _render_compact_artifact(title: str, body: str, meta: str = "") -> str:
    meta_html = f'  <em>{_html.escape(meta)}</em>' if meta else ""
    return (
        '<div class="compact-artifact">'
        f'  <span>{_html.escape(title)}</span>'
        f'  <b>{_html.escape(body)}</b>'
        f'{meta_html}'
        '</div>'
    )


def _render_focus_note(title: str, body: str, meta: str = "") -> str:
    return (
        '<div class="focus-note">'
        f'  <span>{_html.escape(title)}</span>'
        f'  <b>{_html.escape(body)}</b>'
        f'  <p>{_html.escape(meta)}</p>'
        '</div>'
    )


def _resolve_intel_pages(ir: dict | None) -> int:
    """Return the page count tied to the current briefing, not the live slider."""
    ir = ir or {}
    stats = ir.get("stats", {}) or {}
    for candidate in (
        stats.get("pages"),
        stats.get("pages_requested"),
        ir.get("pages"),
        ir.get("pages_requested"),
    ):
        if candidate:
            return int(candidate)

    # Legacy caches created before page metadata existed. A capped 300-title
    # briefing almost always came from a deeper 10-page run in this app.
    title_count = int(stats.get("titles_count", 0) or 0)
    if title_count >= 280:
        return 10

    return int(st.session_state.get("intel_pages", 3) or 3)


def _render_read_digest() -> str:
    ir = st.session_state.get("intel_result", {}) or {}
    gallery_id = (
        st.session_state.get("intel_gallery_id")
        or st.session_state.get("target_gallery_id")
        or "대기"
    )
    gallery_label = _gallery_display_name(gallery_id)
    pages = _resolve_intel_pages(ir)
    summary = _studio_clip(ir.get("ai_analysis") or ir.get("summary") or "", 130)
    summary_html = f'<p>{_html.escape(summary)}</p>' if summary else ""
    return (
        '<div class="read-digest">'
        '  <span>읽은 대상</span>'
        f'  <b>{_html.escape(gallery_label)}</b>'
        f'  <em>{_html.escape(str(gallery_id))} · {pages}페이지</em>'
        f'  {summary_html}'
        '</div>'
    )


def _context_timestamp(gallery_id: str, type_label: str) -> float | None:
    cache = st.session_state.get("intel_cache", {}) or {}
    cache_entry = cache.get(intel_cache.cache_key(gallery_id, type_label)) if gallery_id else None
    if cache_entry and cache_entry.get("ts"):
        return float(cache_entry["ts"])
    if _ltc_restore and (not gallery_id or _ltc_restore.get("gallery_id") == gallery_id):
        if _ltc_restore.get("ts"):
            return float(_ltc_restore["ts"])
    ts = st.session_state.get("_intel_requested_at")
    return float(ts) if ts else None


def _format_context_timestamp(ts: float | None) -> str:
    if not ts:
        return "이번 세션"
    return datetime.datetime.fromtimestamp(ts).strftime("%m/%d %H:%M 기준")


def _current_posting_rhythm() -> dict:
    ir = st.session_state.get("intel_result", {}) or {}
    rhythm = ir.get("posting_rhythm") or {}
    return rhythm if isinstance(rhythm, dict) else {}


def _rhythm_recommendation_minutes(rhythm: dict | None = None) -> int | None:
    source = rhythm if rhythm is not None else _current_posting_rhythm()
    try:
        value = int(source.get("recommended_minutes") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _format_posting_rhythm_inline(rhythm: dict | None = None) -> str:
    source = rhythm if rhythm is not None else _current_posting_rhythm()
    if not source or not source.get("interval_count"):
        return "분석 전"
    avg = board_rhythm.format_seconds(source.get("average_seconds"))
    median = board_rhythm.format_seconds(source.get("median_seconds"))
    rec = source.get("recommended_minutes") or "-"
    return f"평균 {avg} · 중앙 {median} · 추천 {rec}분"


def _render_execution_context() -> str:
    ir = st.session_state.get("intel_result", {}) or {}
    stats = ir.get("stats", {}) or {}
    if not ir and not st.session_state.get("intel_running"):
        return (
            '<div class="run-context-card is-empty">'
            '  <div class="run-context-kicker">실행 정보</div>'
            '</div>'
        )
    gallery_id = (
        st.session_state.get("target_gallery_id")
        or st.session_state.get("intel_gallery_id")
        or "대기"
    )
    gallery_label = _gallery_display_name(gallery_id)
    gallery_heading_html = (
        f'  <h3>{_html.escape(gallery_label)}</h3>'
        if gallery_label
        else ""
    )
    type_label = ui_options.normalize_gallery_type_label(
        st.session_state.get("target_type_label", ui_options.DEFAULT_GALLERY_TYPE_LABEL)
    )
    pages = _resolve_intel_pages(ir)
    read_at = _format_context_timestamp(_context_timestamp(str(gallery_id), type_label)) if ir else "읽기 전"
    briefing_full = " ".join(str(ir.get("ai_analysis") or ir.get("summary") or "").strip().split())
    briefing_html = (
        '<details class="run-context-brief">'
        '  <summary>브리핑 보기</summary>'
        f'  <p>{_html.escape(briefing_full)}</p>'
        '</details>'
        if briefing_full else ""
    )
    counts = (
        f'제목 {int(stats.get("titles_count", 0) or 0)} · '
        f'댓글 {int(stats.get("comments_count", 0) or 0)} · '
        f'키워드 {int(stats.get("keywords_found", 0) or 0)}'
        if ir else "읽기 전"
    )
    rhythm_html = ""
    rhythm = _current_posting_rhythm()
    if rhythm and rhythm.get("interval_count"):
        rhythm_html = (
            f'    <span>글 간격</span><b>{_html.escape(_format_posting_rhythm_inline(rhythm))}</b>'
        )
    return (
        '<div class="run-context-card">'
        '  <div class="run-context-kicker">실행 정보</div>'
        f'{gallery_heading_html}'
        '  <div class="run-context-grid">'
        f'    <span>ID</span><b>{_html.escape(str(gallery_id))}</b>'
        f'    <span>종류</span><b>{_html.escape(type_label)}</b>'
        f'    <span>읽은 양</span><b>{pages}페이지</b>'
        f'    <span>시각</span><b>{_html.escape(read_at)}</b>'
        f'    <span>수집</span><b>{_html.escape(counts)}</b>'
        f'{rhythm_html}'
        '  </div>'
        f'  {briefing_html}'
        '</div>'
    )


def _render_stack_intel_actions() -> None:
    """Keep result actions in the left stack so the main briefing card stays clean."""

    ir = st.session_state.get("intel_result")
    if not ir:
        return

    intel_gid = st.session_state.get("intel_gallery_id", "") or st.session_state.get("target_gallery_id", "")
    sentiment = ir.get("sentiment", "알 수 없음")
    can_use_topic = ui_formatters.has_briefing_topic_source(ir)

    st.markdown('<div class="stack-intel-actions-marker"></div>', unsafe_allow_html=True)
    if st.button(
        "주제로 사용",
        key="stack_use_as_topic_btn",
        use_container_width=True,
        disabled=not can_use_topic,
    ):
        _queue_ai_briefing_topic(ir)
        st.rerun(scope="app")

    if st.button(
        "원본 글 모음 열기" if not st.session_state.get("_intel_raw_open") else "원본 글 모음 닫기",
        key="stack_intel_raw_toggle_btn",
        use_container_width=True,
    ):
        st.session_state["_intel_raw_open"] = not st.session_state.get("_intel_raw_open", False)
        st.rerun(scope="app")


def _render_stack_review_actions() -> None:
    """Pin review launch actions to the left stack."""

    scripts = st.session_state.get("review_scripts", []) or []
    if not scripts or st.session_state.get("swarm_running"):
        return

    valid = [s for s in scripts if not s.get("_failed")]
    failed_count = len(scripts) - len(valid)
    if st.session_state.get("wave_test_mode"):
        completed = len(st.session_state.get("rehearsal_runs", []) or [])
        st.markdown(
            '<div class="stack-review-actions">'
            '  <span>리허설 완료</span>'
            f'  <b>{completed}사이클</b>'
            f'  <em>마지막 묶음 {len(valid)}개</em>'
            '</div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "리허설 결과 비우기",
            key="stack_rehearsal_discard_btn",
            use_container_width=True,
        ):
            st.session_state.review_ready = False
            st.session_state.review_scripts = []
            st.session_state.rehearsal_runs = []
            st.session_state.test_summaries = []
            st.session_state["_rehearsal_complete"] = False
            st.rerun(scope="app")
        return

    st.markdown(
        '<div class="stack-review-actions">'
        '  <span>검토 액션</span>'
        f'  <b>{len(valid)}개 준비</b>'
        f'  <em>{failed_count}개 제외</em>'
        '</div>',
        unsafe_allow_html=True,
    )
    if st.button(
        f"발행 시작 — {len(valid)}개",
        key="stack_confirm_publish_btn",
        use_container_width=True,
        disabled=not valid,
    ):
        error = _launch_review_scripts(st.session_state)
        if error:
            st.error(f"⚠️ {error}")
            return
        st.rerun(scope="app")

    if st.button(
        "원고 폐기",
        key="stack_review_discard_btn",
        use_container_width=True,
        help="현재 원고를 버리고 다시 생성합니다.",
    ):
        st.session_state.review_ready = False
        st.session_state.review_scripts = []
        st.rerun(scope="app")


def _render_read_controls() -> bool:
    st.text_input(
        "게시판 ID",
        key="target_gallery_id",
        placeholder="예: baseball_new9",
        help="분석하고 글을 올릴 게시판 ID입니다.",
    )
    st.selectbox(
        "게시판 종류",
        options=ui_options.GALLERY_TYPE_OPTIONS,
        key="target_type_label",
        help="정규 게시판인지 마이너 게시판인지 선택합니다.",
    )
    pages_now = st.slider(
        "읽을 페이지",
        min_value=1,
        max_value=20,
        key="intel_pages",
        help="숫자가 클수록 더 깊게 읽지만 시간이 더 걸립니다.",
    )
    st.markdown(
        f'<div class="slider-readout"><span>현재 선택</span><b>{int(pages_now)}페이지</b></div>',
        unsafe_allow_html=True,
    )
    clicked = st.button(
        "게시판 읽기" if not _intel_is_running else "읽는 중",
        key="intel_fire_btn",
        disabled=_workbench_intel_disabled,
        use_container_width=True,
    )
    _render_recent_manage_panel()
    return clicked


def _render_topic_controls(*, height: int = 210) -> None:
    st.text_area(
        "브리핑",
        key="swarm_topic_input",
        placeholder="게시판에서 읽은 분위기와 씨앗 떡밥이 들어갑니다.",
        height=max(150, height - 100),
    )
    st.text_area(
        "작문 지시",
        key="swarm_guidance_input",
        placeholder="피해야 할 표현, 안전한 접근 각도, 생성 기준이 들어갑니다.",
        height=95,
    )


def _render_prompt_snapshot() -> str:
    """Render the frozen briefing/guidance used by the current draft worker."""

    cfg = st.session_state.get("_batch_gen_config", {}) or {}
    briefing = str(cfg.get("briefing") or st.session_state.get("swarm_topic_input", "") or "").strip()
    guidance = str(cfg.get("guidance") or st.session_state.get("swarm_guidance_input", "") or "").strip()

    def _block(label: str, value: str, *, muted: bool = False) -> str:
        if not value:
            value = "입력된 내용 없음"
            muted = True
        safe_cls = " is-muted" if muted else ""
        return (
            f'<div class="prompt-snapshot-block{safe_cls}">'
            f'  <span>{_html.escape(label)}</span>'
            f'  <p>{_html.escape(value)}</p>'
            '</div>'
        )

    return (
        '<div class="prompt-snapshot">'
        f'{_block("브리핑", briefing)}'
        f'{_block("작문 지시", guidance, muted=not guidance)}'
        '</div>'
    )


def _render_main_execution_modes() -> None:
    """Keep loop and rehearsal modes visible in the persistent left workbench."""

    def _toggle_infinite_mode() -> None:
        enabled = not bool(
            st.session_state.get("swarm_infinite", False)
        )
        st.session_state["swarm_infinite"] = enabled
        if enabled:
            st.session_state["wave_test_mode"] = False
        cfg = dict(st.session_state.get("_batch_gen_config", {}) or {})
        if not cfg:
            return
        cfg["infinite"] = enabled
        cfg["wave_test_mode"] = False
        cfg["rehearsal"] = False
        if enabled:
            cfg["wave_count"] = 10
        st.session_state["_batch_gen_config"] = cfg

    def _toggle_rehearsal_mode() -> None:
        enabled = not bool(
            st.session_state.get("wave_test_mode", False)
        )
        st.session_state["wave_test_mode"] = enabled
        if enabled:
            st.session_state["swarm_infinite"] = False
        cfg = dict(st.session_state.get("_batch_gen_config", {}) or {})
        if not cfg:
            return
        cfg["wave_test_mode"] = enabled
        cfg["rehearsal"] = enabled
        cfg["infinite"] = False
        if enabled:
            cfg["wave_count"] = 10
        st.session_state["_batch_gen_config"] = cfg

    with st.container(key="main_execution_modes"):
        mode_cols = st.columns(2, gap="small")
        with mode_cols[0]:
            infinite_enabled = bool(st.session_state.get("swarm_infinite", False))
            st.button(
                "∞ 무한 실행",
                key="toggle_infinite_mode_card",
                on_click=_toggle_infinite_mode,
                help="켜면 원고 생성과 발행이 끝난 뒤 다음 묶음을 자동으로 이어갑니다.",
                use_container_width=True,
                type="primary" if infinite_enabled else "secondary",
            )
        with mode_cols[1]:
            rehearsal_enabled = bool(st.session_state.get("wave_test_mode", False))
            st.button(
                "리허설",
                key="toggle_rehearsal_mode_card",
                on_click=_toggle_rehearsal_mode,
                help="실제 게시 없이 생성·검증·순환 흐름을 빠르게 점검합니다.",
                use_container_width=True,
                type="primary" if rehearsal_enabled else "secondary",
            )
        if st.session_state.get("wave_test_mode"):
            mode_text = "직전 원고만 다시 분석하는 유한 사이클"
        elif st.session_state.get("swarm_infinite"):
            mode_text = "다음 묶음 자동 실행"
        else:
            mode_text = "현재 묶음만 실행"
        st.caption(mode_text)


def _render_ops_stability_controls() -> None:
    with st.expander("안전 정지", expanded=False):
        st.number_input(
            "무한 사이클 상한",
            min_value=1,
            max_value=500,
            step=1,
            key="ops_max_infinite_cycles",
            help="무한모드가 이 사이클 수에 도달하면 점검을 위해 멈춥니다.",
        )
        st.number_input(
            "연속 저품질 생성",
            min_value=1,
            max_value=20,
            step=1,
            key="ops_max_consecutive_bad_cycles",
            help="이 횟수만큼 연속으로 생성 품질이 낮으면 무한모드를 중단합니다.",
        )
        st.number_input(
            "발행 실패 허용",
            min_value=0,
            max_value=100,
            step=1,
            key="ops_max_publish_failures",
            help="0이면 발행 실패 누적 정지를 사용하지 않습니다.",
        )
        st.number_input(
            "댓글 경고 허용",
            min_value=0,
            max_value=100,
            step=1,
            key="ops_max_feedback_alerts",
            help="발행 ID 기준 감시 댓글에서 경고가 누적되면 멈춥니다. 0이면 비활성화합니다.",
        )
        st.checkbox(
            "Gemini 결제 문제 시 정지",
            key="ops_stop_on_billing_issue",
            help="크레딧/결제 오류가 감지되면 수집 결과를 보존하고 무한 실행을 멈춥니다.",
        )
        st.checkbox(
            "원본 수집 없음 시 정지",
            key="ops_stop_on_empty_source",
            help="게시판 원본이 전혀 수집되지 않은 상태에서는 다음 실행을 막습니다.",
        )


def _render_run_controls(*, compact: bool = False) -> bool:
    if compact:
        st.markdown(
            '<div class="run-controls-compact">'
            f'<div class="rail-state {_workbench_state_cls}">{_html.escape(_workbench_state_text)}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return False

    if st.session_state.get("wave_test_mode", False):
        with st.container(key="rehearsal_settings_panel"):
            st.markdown(
                '<div class="rehearsal-settings-title">리허설 설정</div>',
                unsafe_allow_html=True,
            )
            st.number_input(
                "리허설 사이클",
                min_value=rehearsal_flow.MIN_CYCLE_LIMIT,
                max_value=rehearsal_flow.MAX_CYCLE_LIMIT,
                step=1,
                key="rehearsal_cycle_limit",
                help="사이클마다 원고 10개를 만들고 그 10개만 분석해 다음 사이클을 이어갑니다.",
            )
            st.caption("사이클당 10개 · 실제 게시판 발행 없음")
    else:
        st.number_input(
            "원고 수",
            min_value=1,
            max_value=50,
            step=1,
            key="swarm_wave_count",
            help="이번에 준비할 원고 개수입니다.",
            disabled=st.session_state.get("swarm_infinite", False),
        )
    _interval_unit = "초(리허설)" if st.session_state.get("wave_test_mode", False) else "분"
    st.number_input(
        f"발행 간격 ({_interval_unit})",
        min_value=1,
        max_value=180,
        step=1,
        key="publish_interval_minutes",
        help="실제 발행은 이 간격마다 순차 업로드합니다. 리허설 모드에서는 같은 숫자를 초로 봅니다.",
    )
    _rhythm = _current_posting_rhythm()
    _rec_minutes = _rhythm_recommendation_minutes(_rhythm)
    if _rec_minutes:
        st.caption(f"게시판 리듬: {_format_posting_rhythm_inline(_rhythm)}")
        st.button(
            f"평균 간격 적용 · {_rec_minutes}분",
            key="apply_board_rhythm_interval_btn",
            use_container_width=True,
            help="최근 수집한 원본 글 작성시간의 절삭 평균을 발행 간격으로 사용합니다.",
            on_click=lambda: st.session_state.update(
                publish_interval_minutes=operator_settings.normalize_publish_interval_minutes(
                    _rec_minutes
                )
            ),
        )
    else:
        st.button(
            "평균 간격 적용",
            key="apply_board_rhythm_interval_btn_disabled",
            use_container_width=True,
            disabled=True,
            help="게시판을 먼저 읽으면 최근 글 작성시간 기반 추천 간격이 계산됩니다.",
        )
    clicked = st.button(
        _workbench_draft_label,
        key="make_drafts_btn",
        use_container_width=True,
        type="primary",
        disabled=_workbench_fire_disabled,
    )
    st.markdown(
        f'<div class="rail-state {_workbench_state_cls}">{_html.escape(_workbench_state_text)}</div>',
        unsafe_allow_html=True,
    )
    return clicked

if _intel_is_running:
    _layout_weights = [0.18, 0.42, 0.40]
elif _is_generating:
    _layout_weights = [0.20, 0.54, 0.26]
elif _active_stage == "review":
    _layout_weights = [0.20, 0.54, 0.26]
elif _active_stage == "publish":
    _layout_weights = [0.18, 0.42, 0.40]
else:
    _layout_weights = [0.20, 0.54, 0.26]

_log_focus_mode = bool(_intel_is_running or _is_generating or _is_running)
if _is_running:
    _log_panel_height = 860
elif _log_focus_mode:
    _log_panel_height = 820
else:
    _log_panel_height = 680
fire_clicked = False

stack_col, work_col, log_col = st.columns(_layout_weights, gap="medium")
with stack_col:
    left_html = (
        '<div class="stack-panel-marker"></div>'
        + _render_execution_context()
        + _render_ops_summary_card()
    )
    if _is_generating or _has_drafts or _active_stage in ("review", "publish"):
        _review_valid_count = sum(
            1 for _s in (st.session_state.get("review_scripts", []) or [])
            if not _s.get("_failed")
        )
        left_html += (
            '<div class="stage-summary-list is-minimal">'
            + _stage_summary("03", "원고", f"{_review_valid_count}개", _review_state)
            + _stage_summary("04", "발행", f"{st.session_state.get('posts_success', 0)} 성공", _publish_state)
            + '</div>'
        )
    st.markdown(left_html, unsafe_allow_html=True)
    _render_main_execution_modes()
    _render_ops_stability_controls()
    if _active_stage == "review" and not _is_generating:
        _render_stack_review_actions()
    _render_stack_intel_actions()
    _render_review_package_copy_button()
    if _active_stage != "read":
        _render_recent_manage_panel()
    if _active_stage == "write" and not (_is_generating or _is_running):
        fire_clicked = _render_run_controls(compact=False)
    if _active_stage != "read":
        st.text_input(
            "게시판",
            key="target_gallery_id",
            placeholder="예: universe",
            help="브리핑 이후에도 발행 대상 게시판을 여기서 확인하고 수정합니다.",
        )
        st.selectbox(
            "종류",
            options=ui_options.GALLERY_TYPE_OPTIONS,
            key="target_type_label",
            help="정규 게시판인지 마이너 게시판인지 확인합니다.",
        )

with work_col:
    if _active_stage == "read":
        st.markdown(
            '<div class="active-panel-marker active-stage-read"></div>'
            '<div class="panel-heading"><span>01</span><b>게시판 읽기</b></div>',
            unsafe_allow_html=True,
        )
        _intel_fire = _render_read_controls()
        if _intel_is_running or st.session_state.get("intel_result"):
            _intel_results_fragment()
    elif _active_stage == "intel":
        st.markdown(
            '<div class="active-panel-marker active-stage-intel"></div>'
            '<div class="panel-heading"><span>01</span><b>게시판 읽는 중</b></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            _render_compact_artifact(
                "진행",
                f"{st.session_state.get('target_gallery_id', '') or '게시판'} · {st.session_state.get('intel_pages', 3)}페이지",
                "",
            ),
            unsafe_allow_html=True,
        )
    elif _active_stage == "review":
        _review_heading = "초안 작성" if _is_generating else "검토할 원고"
        st.markdown(
            '<div class="active-panel-marker active-stage-review"></div>'
            f'<div class="panel-heading"><span>03</span><b>{_html.escape(_review_heading)}</b></div>',
            unsafe_allow_html=True,
        )
        if _is_generating:
            _gen_total = int(
                st.session_state.get("swarm_wave_total")
                or (st.session_state.get("_batch_gen_config", {}) or {}).get("wave_count")
                or st.session_state.get("swarm_wave_count", 0)
                or 0
            )
            st.markdown(
                _render_compact_artifact(
                    "작성 중",
                    f"{_gen_total}개 원고",
                    "",
                ),
                unsafe_allow_html=True,
            )
            st.markdown(_render_prompt_snapshot(), unsafe_allow_html=True)
        elif st.session_state.get("review_ready") and not st.session_state.get("swarm_running"):
            _review_board_fragment()
        else:
            st.markdown('<div class="pd-empty">검토할 원고가 아직 준비되지 않았습니다.</div>', unsafe_allow_html=True)
    elif _active_stage == "publish":
        st.markdown(
            '<div class="active-panel-marker active-stage-publish"></div>'
            '<div class="panel-heading"><span>04</span><b>발행 흐름</b></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            _render_publish_draft_stack(
                st.session_state.get("review_scripts", []) or [],
                current_wave=int(st.session_state.get("swarm_wave_current", 0) or 0),
                height_px=760,
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="active-panel-marker active-stage-write"></div>'
            '<div class="panel-heading"><span>02</span><b>주제와 브리핑</b></div>',
            unsafe_allow_html=True,
        )
        _render_topic_controls(height=280)
        if _intel_is_running or st.session_state.get("intel_result"):
            _intel_results_fragment()

with log_col:
    st.markdown(
        '<div class="log-panel-marker"></div>'
        '<div class="panel-heading"><span>LOG</span><b>실행 로그</b></div>',
        unsafe_allow_html=True,
    )
    if _intel_is_running:
        _intel_results_fragment()
    elif _is_generating:
        if st.button("작성 중단", key="stop_batch_btn_top", use_container_width=True):
            if st.session_state.get("batch_gen_stop_event"):
                st.session_state.batch_gen_stop_event.set()
                st.session_state.swarm_log.append("[BATCH] 생성 중단 요청 전송됨")
                st.rerun()
        _batch_gen_fragment()
    elif _is_running:
        if st.button("발행 중단", key="stop_publish_btn_top", use_container_width=True):
            if st.session_state.get("swarm_stop_event"):
                st.session_state.swarm_stop_event.set()
                st.session_state.swarm_log.append("[SWARM] 중단 요청 전송됨")
                st.rerun()
        _publish_log_fragment(height_px=_log_panel_height)
    elif _live_logs:
        render_activity_panel_component(
            _live_logs,
            title=_live_title,
            height_px=_log_panel_height,
            limit=_current_live_log_limit(),
        )
    else:
        render_activity_panel_component(
            [],
            title="대기",
            height_px=_log_panel_height,
            limit=8,
        )

_gallery_id = st.session_state.get("target_gallery_id", "").strip()
_gallery_type_label = st.session_state.get(
    "target_type_label",
    ui_options.DEFAULT_GALLERY_TYPE_LABEL,
)
_gallery_type = ui_options.gallery_type_for_label(_gallery_type_label)
st.session_state.intel_gallery_id = _gallery_id
st.session_state.intel_type_label = ui_options.normalize_gallery_type_label(_gallery_type_label)

_topic_val = st.session_state.get("swarm_topic_input", "").strip()
_neural_tone = ui_options.tone_for_label(
    st.session_state.get("target_tone_label", ui_options.DEFAULT_TONE_LABEL)
)
_tone_label = ui_options.normalize_tone_label(
    st.session_state.get("target_tone_label", ui_options.DEFAULT_TONE_LABEL)
)
_length = st.session_state.get("target_length", ui_options.DEFAULT_LENGTH_LABEL)
_headless = st.session_state.get("target_headless", True)
_iv_min = st.session_state.get("wave_interval_min", 1)
_iv_max = st.session_state.get("wave_interval_max", 3)
_test_mode = st.session_state.get("wave_test_mode", False)
_interval_str = f"{_iv_min}~{_iv_max}초" if _test_mode else f"{_iv_min}~{_iv_max}분"
_intel_btn_disabled = not has_any_key or not _gallery_id or _intel_is_running
_fire_disabled = not has_any_key or not _gallery_id or not _topic_val or _any_busy

_ick = intel_cache.cache_key(_gallery_id, _gallery_type_label)
_icached = st.session_state.intel_cache.get(_ick)
_icache_age = intel_cache.cache_age_seconds(_icached)
_icache_valid = intel_cache.is_cache_fresh(_icached)
_requested_pages_now = int(st.session_state.get("intel_pages", 3) or 3)
if _icache_valid and _icached:
    _cached_result = _icached.get("result") or {}
    _cached_stats = _cached_result.get("stats", {}) or {}
    _cached_pages = 0
    for _page_candidate in (
        _cached_stats.get("pages"),
        _cached_stats.get("pages_requested"),
        _cached_result.get("pages"),
        _cached_result.get("pages_requested"),
    ):
        if _page_candidate:
            _cached_pages = int(_page_candidate)
            break
    if not _cached_pages and int(_cached_stats.get("titles_count", 0) or 0) >= 280:
        _cached_pages = 10
    if not _cached_pages:
        _cached_pages = 3
    if _cached_pages < _requested_pages_now:
        _icache_valid = False

main_right = st.container()

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
                'letter-spacing:1px;padding:6px 0">계속 이어가기 실행 중</div>',
                unsafe_allow_html=True,
            )
        with _ks_col_btn:
            st.button("루프 중단", key="infinite_killswitch_btn",
                      on_click=_do_killswitch,
                      use_container_width=True, type="primary",
                      help="현재 작업이 정리되는 대로 자동 반복을 중단합니다")

    # 하단 중복 결과/발행 패널은 제거한다.
    # 현재 단계의 결과와 로그는 상단 3분할 작업대 안에서만 렌더링한다.


# ══════════════════════════════════════════════════════════════════════════════
# 대본 제작 버튼 — 배치 생성 워커 시작 (포스팅 없음)
# ══════════════════════════════════════════════════════════════════════════════
if fire_clicked:
    _topic    = st.session_state.get("swarm_topic_input", "").strip()
    _guidance = st.session_state.get("swarm_guidance_input", "").strip()
    _worker_topic = (
        _topic + ("\n\n[작문 지시]\n" + _guidance if _guidance else "")
    ).strip()
    _w_count  = st.session_state.get("swarm_wave_count", 3)
    _infinite = bool(st.session_state.get("swarm_infinite", False))
    _rehearsal = bool(st.session_state.get("wave_test_mode", False))
    _style_profile = (st.session_state.get("intel_result") or {}).get("style_profile")
    _composition_profile = (st.session_state.get("intel_result") or {}).get("composition_profile")

    if not has_any_key:
        st.error("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. 프로젝트 루트의 .env 파일을 확인하고 앱을 재시작하세요.")
    elif not _topic:
        st.error("⚠️ 주제를 입력하세요.")
    elif not _gallery_id:
        st.error("⚠️ 글을 올릴 게시판이 비어 있습니다. 상단의 게시판 입력칸을 채워주세요.")
    else:
        # Phase 10: 무한 모드 변수 누수 방지 — UI 캐시값(swarm_wave_count)과 무관하게 10 강제
        # min(_w_count, 10) 패턴은 유저가 3으로 설정한 채 infinite ON 하면 3개만 도는 버그 유발.
        _actual_count = 10 if (_infinite or _rehearsal) else _w_count
        _rehearsal_cycle_limit = rehearsal_flow.normalize_cycle_limit(
            st.session_state.get("rehearsal_cycle_limit")
        )
        _intel_result_for_anchor = st.session_state.get("intel_result") or {}
        _rehearsal_anchor_posts = (
            list(_intel_result_for_anchor.get("raw_posts") or [])
            if _rehearsal
            else []
        )
        _rehearsal_anchor_topic = str(_topic or _worker_topic or "").strip()
        _run_mode = "rehearsal" if _rehearsal else ("infinite" if _infinite else "draft")
        observability.start_run(
            st.session_state,
            mode=_run_mode,
            gallery_id=_gallery_id,
            target_count=_actual_count,
            reset=True,
            detail=(
                f"topic_chars={len(_topic)} guidance_chars={len(_guidance)} "
                f"cycles={_rehearsal_cycle_limit if _rehearsal else 1}"
            ),
        )
        st.session_state["run_prompt_versions"] = [
            {
                "ts": time.time(),
                "mode": _run_mode,
                "topic_preview": observability.compact_text(_topic, 180),
                "guidance_preview": observability.compact_text(_guidance, 180),
                "style_profile": bool(_style_profile),
                "composition_profile": bool(_composition_profile),
            }
        ]
        st.session_state["_batch_cycle_count"] = 1
        observability.append_event(
            st.session_state,
            kind="cycle_start",
            title="cycle 1 generation start",
            detail=f"target={_actual_count} rehearsal={_rehearsal}",
            status="running",
            cycle=1,
            metrics={"target": _actual_count},
        )

        # 무한 모드 재배치를 위한 설정 저장
        st.session_state["_batch_gen_config"] = {
            "api_key":            _GEMINI_API_KEY,
            "topic":              _worker_topic,
            "briefing":           _topic,
            "guidance":           _guidance,
            "wave_count":         _actual_count,
            "gallery_id":         _gallery_id,
            "gallery_type":       _gallery_type,
            "tone":               _neural_tone,
            "length":             _length,
            "headless":           _headless,
            "infinite":           _infinite,
            "style_profile":      _style_profile,
            "composition_profile": _composition_profile,
            "wave_interval_min":  st.session_state.get("wave_interval_min", 1),
            "wave_interval_max":  st.session_state.get("wave_interval_max", 3),
            "publish_interval_minutes": st.session_state.get("publish_interval_minutes", 3),
            "wave_test_mode":     _rehearsal,
            "rehearsal":          _rehearsal,
            "rehearsal_cycle":    1,
            "rehearsal_cycle_limit": _rehearsal_cycle_limit,
            "rehearsal_anchor_posts": _rehearsal_anchor_posts,
            "rehearsal_anchor_topic": _rehearsal_anchor_topic,
            "ai_disclosure_enabled": False,
            "ai_disclosure_marker": operator_settings.DEFAULT_PUBLIC_AI_MARKER,
            "ai_comment_watch_limit": operator_settings.normalize_ai_comment_watch_limit(
                st.session_state.get(
                    "ai_comment_watch_limit",
                    operator_settings.DEFAULT_AI_COMMENT_WATCH_LIMIT,
                )
            ),
        }

        st.session_state.swarm_log            = []
        _active_modes = []
        if _infinite:
            _active_modes.append("무한 실행")
        if _rehearsal:
            _active_modes.append("리허설")
        st.session_state.swarm_log.append(
            "[MODE] 실행 모드 — "
            + (" + ".join(_active_modes) if _active_modes else "단일 묶음")
        )
        if _infinite:
            st.session_state.swarm_log.append(
                "[∞] 무한모드 시작 — 생성과 발행이 끝나면 다음 묶음을 자동으로 이어갑니다."
            )
        if _rehearsal:
            st.session_state.swarm_log.append(
                f"[REHEARSAL] 시작 — {_rehearsal_cycle_limit}사이클 × 10개, "
                f"실제 게시 없이 원고와 원본 앵커 {len(_rehearsal_anchor_posts)}개를 재분석합니다."
            )
        st.session_state["rehearsal_runs"] = []
        st.session_state["test_summaries"] = []
        st.session_state["_test_wave_counter"] = 0
        st.session_state["_rehearsal_complete"] = False
        st.session_state.swarm_preview_title  = ""
        st.session_state.swarm_preview_content = ""
        st.session_state.swarm_wave_total     = _actual_count
        st.session_state.swarm_wave_current   = 0
        st.session_state.review_scripts       = []
        st.session_state.review_ready         = False
        st.session_state["_infinite_refill_scripts"] = []
        st.session_state["_infinite_refill_round"] = 0
        st.session_state.batch_generating     = True

        _bgq:  queue.Queue     = queue.Queue()
        _bgev: threading.Event = threading.Event()
        st.session_state.batch_gen_queue      = _bgq
        st.session_state.batch_gen_stop_event = _bgev

        threading.Thread(
            target=_batch_gen_worker_guarded,
            kwargs={
                "log_q":        _bgq,
                "stop_ev":      _bgev,
                "api_key":      _GEMINI_API_KEY,
                "topic":        _worker_topic,
                "wave_count":   _actual_count,
                "gallery_id":   _gallery_id,
                "gallery_type": _gallery_type,
                "tone":         _neural_tone,
                "length":       _length,
                "infinite":     _infinite,
                "style_profile": _style_profile,
                "composition_profile": _composition_profile,
                "rehearsal":    _rehearsal,
                "rehearsal_cycle": 1,
                "rehearsal_cycle_limit": _rehearsal_cycle_limit,
                "rehearsal_anchor_posts": _rehearsal_anchor_posts,
                "rehearsal_anchor_topic": _rehearsal_anchor_topic,
            },
            daemon=True,
        ).start()

        st.rerun()  # _batch_gen_fragment 폴링 진입


# ══════════════════════════════════════════════
# INTEL FIRE — 분석 워커 시작
# ══════════════════════════════════════════════
if _intel_fire:
    _igid = st.session_state.get("intel_gallery_id", "").strip()
    _igtype_label = st.session_state.get("intel_type_label", _gallery_type_label)
    _igtype_now = ui_options.gallery_type_for_label(_igtype_label)

    if not has_any_key:
        st.error("⚠️ GEMINI_API_KEY가 설정되지 않았습니다. 프로젝트 루트의 .env 파일을 확인하고 앱을 재시작하세요.")
    elif not _igid:
        st.error("⚠️ 갤러리 ID를 입력하세요.")
    elif _icache_valid and _icached:
        # 캐시 히트 → 워커 없이 즉시 표시
        st.session_state.intel_result = _icached["result"]
        st.session_state["_intel_requested_at"] = _icached.get("ts", time.time())
        st.rerun()
    else:
        st.session_state.intel_log     = []
        st.session_state.intel_result  = None
        st.session_state.intel_running = True
        st.session_state["_intel_requested_at"] = time.time()
        observability.start_run(
            st.session_state,
            mode="read",
            gallery_id=_igid,
            target_count=int(st.session_state.get("intel_pages", 3) or 3),
            reset=True,
            detail=f"type={_igtype_now} pages={st.session_state.get('intel_pages', 3)}",
        )

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
