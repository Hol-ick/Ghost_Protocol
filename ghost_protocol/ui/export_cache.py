"""Streamlit cache wrappers for dashboard export payloads."""

from __future__ import annotations

import streamlit as st

from ghost_protocol.application import data_exports


@st.cache_data(ttl=300, show_spinner=False)
def cached_posts_csv(gallery_id: str) -> tuple[bytes, int]:
    """Return cached posts CSV bytes for browser download."""
    return data_exports.build_posts_csv(gallery_id)


@st.cache_data(ttl=300, show_spinner=False)
def cached_comments_csv(gallery_id: str) -> tuple[bytes, int]:
    """Return cached comments CSV bytes for browser download."""
    return data_exports.build_comments_csv(gallery_id)
