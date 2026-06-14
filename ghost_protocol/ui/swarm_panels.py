"""Streamlit panel renderers for the Swarm monitor."""

from __future__ import annotations

from collections.abc import MutableMapping

import streamlit as st

from ghost_protocol.ui import formatters
from ghost_protocol.ui.session_state import clear_test_summaries


def render_test_summaries_panel(session_state: MutableMapping) -> None:
    """Render the test-mode cycle summary panel."""
    test_summaries = session_state.get("test_summaries", [])
    if not session_state.get("wave_test_mode") or not test_summaries:
        return

    st.markdown(
        '<div class="section-hdr">🧪 TEST — 사이클 요약</div>',
        unsafe_allow_html=True,
    )
    log_path = session_state.get("_test_log_path")
    if log_path:
        st.caption(formatters.format_test_log_caption(log_path, len(test_summaries)))

    st.text_area(
        "테스트 요약",
        value="\n".join(str(summary) for summary in test_summaries),
        height=180,
        key="swarm_panel_test_summaries_text_area",
        label_visibility="collapsed",
    )
    if st.button("🗑️ 요약 초기화", key="clear_test_summaries"):
        clear_test_summaries(session_state, reset_log_path=True)
        st.rerun(scope="app")


def render_log_copy_panel(logs: list) -> None:
    """Render the collapsed recent-log copy panel."""
    if not logs:
        return

    with st.expander("📋 로그 복사", expanded=False):
        st.text_area(
            "로그 복사",
            value=formatters.format_log_copy_text(logs),
            height=260,
            key="swarm_panel_log_copy_text_area",
            label_visibility="collapsed",
        )
