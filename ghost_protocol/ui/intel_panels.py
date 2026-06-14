"""Streamlit panel renderers for the Intel dashboard."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
import streamlit as st

from ghost_protocol.application import data_exports
from ghost_protocol.ui import export_cache
from ghost_protocol.ui import formatters
from ghost_protocol.ui import intel_view_model


def render_raw_post_debug_panel(
    *,
    raw_posts: Iterable[dict] | None,
    ai_post_nos: Iterable[str] | None,
    intel_gallery_id: str,
    target_gallery_id: str,
) -> None:
    """Render the raw-post debug dataframe used to inspect bot markings."""
    posts = list(raw_posts or [])
    if not posts:
        return

    ai_nos = {str(post_no) for post_no in (ai_post_nos or set())}
    with st.expander(f"🔍 수집 게시글 원본 ({len(posts)}개) — 봇 마킹 확인", expanded=False):
        rows = intel_view_model.build_raw_post_debug_rows(posts, ai_nos)
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(intel_view_model.raw_post_debug_caption(
            ai_post_nos_count=len(ai_nos),
            intel_gallery_id=intel_gallery_id,
            target_gallery_id=target_gallery_id,
            raw_post_count=len(posts),
        ))


def render_db_export_panel(gallery_id: str) -> None:
    """Render the DB CSV export panel for the current Intel gallery."""
    export_gid = gallery_id.strip()
    if not export_gid:
        return

    post_count, comment_count = data_exports.get_export_counts(export_gid)
    with st.expander(
        f"📥 DB 원본 데이터 내보내기 — 게시글 {post_count:,}개 · 댓글 {comment_count:,}개",
        expanded=False,
    ):
        hard_limit = data_exports.EXPORT_HARD_LIMIT
        st.caption(formatters.format_export_limit_caption(
            post_count=post_count,
            comment_count=comment_count,
            hard_limit=hard_limit,
        ))

        post_col, comment_col = st.columns(2)

        with post_col:
            if post_count > 0:
                with st.spinner(f"게시글 CSV 준비 중... ({min(post_count, hard_limit):,}행)"):
                    posts_csv, posts_rows = export_cache.cached_posts_csv(export_gid)
                st.download_button(
                    f"⬇️ 게시글 CSV ({posts_rows:,}행)",
                    data=posts_csv,
                    file_name=f"{export_gid}_posts.csv",
                    mime="text/csv",
                    key="dl_posts_csv",
                    use_container_width=True,
                )
            else:
                st.info("게시글 없음")

        with comment_col:
            if comment_count > 0:
                with st.spinner(f"댓글 CSV 준비 중... ({min(comment_count, hard_limit):,}행)"):
                    comments_csv, comments_rows = export_cache.cached_comments_csv(export_gid)
                st.download_button(
                    f"⬇️ 댓글 CSV ({comments_rows:,}행)",
                    data=comments_csv,
                    file_name=f"{export_gid}_comments.csv",
                    mime="text/csv",
                    key="dl_comments_csv",
                    use_container_width=True,
                )
            else:
                st.info("댓글 없음")
