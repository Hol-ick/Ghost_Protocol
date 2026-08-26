import unittest

from ghost_protocol.ui.formatters import (
    build_test_summary,
    build_generation_guidance,
    build_briefing_topic,
    build_intel_fig,
    compact_text,
    format_activity_log_markdown,
    format_actor_briefing_markdown,
    format_review_package_markdown,
    format_export_limit_caption,
    format_intel_markdown,
    format_log_copy_text,
    format_scripts_markdown,
    format_scripts_for_copy,
    format_test_log_caption,
    has_briefing_topic_source,
    normalize_ai_briefing_text,
    render_idle_terminal,
    render_ai_occupation_card,
    render_intel_briefing_card,
    render_compact_intel,
    render_intel_idle_empty,
    render_intel_log_panel,
    render_intel_running_empty,
    render_mission_stat_pill,
    render_situation_summary,
    render_swarm_empty_preview,
    render_swarm_preview_card,
    render_terminal,
)
from ghost_protocol.ui.intel_view_model import build_ai_occupation_view
from ghost_protocol.ui.theme import launchpad_css


class UiFormattersTest(unittest.TestCase):
    def test_terminal_escapes_html(self):
        html = render_terminal(["<script>alert(1)</script>"], height_px=120)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_idle_terminal_escapes_lines(self):
        html = render_idle_terminal(height_px=120, lines=["ready", "<bad>"])
        self.assertIn("ready<br>&lt;bad&gt;", html)
        self.assertNotIn("<bad>", html)

    def test_script_bundle_contains_wave_data(self):
        text = format_scripts_for_copy(
            [{"wave": 1, "persona_name": "Analyst", "tone": "neutral", "title": "T", "content": "C"}]
        )
        self.assertIn("원고 1", text)
        self.assertIn("제목: T", text)

    def test_script_markdown_bundle_contains_wave_data(self):
        text = format_scripts_markdown(
            [{
                "wave": 1,
                "persona_name": "Analyst",
                "tone": "neutral",
                "title": "T",
                "content": "C",
                "target_comments": [{"post_no": "10", "comment": "댓글"}],
            }]
        )
        self.assertIn("# 검토용 원고 모음", text)
        self.assertIn("## 원고 1", text)
        self.assertIn("- 제목: T", text)
        self.assertIn("- #10: 댓글", text)

    def test_script_copy_labels_simulation_only_comment_targets(self):
        scripts = [{
            "wave": 1,
            "persona_name": "Analyst",
            "tone": "neutral",
            "title": "T",
            "content": "C",
            "target_comments": [
                {"post_no": "10", "comment": "candidate", "simulation_only": True},
            ],
        }]

        plain = format_scripts_for_copy(scripts)
        markdown = format_scripts_markdown(scripts)

        self.assertIn("#10 (리허설): candidate", plain)
        self.assertIn("- #10 (리허설): candidate", markdown)

    def test_script_markdown_bundle_includes_failed_candidates(self):
        text = format_scripts_markdown(
            [{
                "wave": 2,
                "persona_name": "Observer",
                "tone": "neutral",
                "_failed": True,
                "_rejected_title": "후보 제목",
                "_rejected_content": "후보 본문",
                "_rejected_comments": [{"post_no": "20", "comment": "댓글 후보"}],
                "_failure_reason": "의미 중복",
            }]
        )

        self.assertIn("- 요청 원고: 1개", text)
        self.assertIn("- 생성 성공: 0개", text)
        self.assertIn("- 생성 실패: 1개", text)
        self.assertIn("# 생성 실패 원고", text)
        self.assertIn("- 후보 제목: 후보 제목", text)
        self.assertIn("후보 본문", text)
        self.assertIn("- #20: 댓글 후보", text)
        self.assertIn("- 실패 사유: 의미 중복", text)

    def test_script_markdown_bundle_keeps_safety_failure_metadata_without_candidate(self):
        text = format_scripts_markdown(
            [{
                "wave": 3,
                "persona_name": "Guarded",
                "tone": "cynical",
                "_failed": True,
                "_failure_reason": "안전 필터",
                "_failure_stage": "safety_filter",
                "_failure_detail": "민감 표현 감지",
                "_failure_attempts": 3,
            }]
        )

        self.assertIn("## 원고 3", text)
        self.assertIn("(복구 가능한 제목 없음)", text)
        self.assertIn("(복구 가능한 본문 없음)", text)
        self.assertIn("- 실패 사유: 안전 필터", text)
        self.assertIn("- 실패 단계: `safety_filter`", text)
        self.assertIn("- 생성 시도: 3회", text)
        self.assertIn("- 상세: 민감 표현 감지", text)

    def test_test_log_caption_uses_basename(self):
        caption = format_test_log_caption("C:/tmp/logs/test_1.txt", 3)
        self.assertEqual(caption, "📁 로그 파일: `logs/test_1.txt`  (3회)")

    def test_log_copy_text_limits_recent_lines(self):
        text = format_log_copy_text(["a", "b", "c"], limit=2)
        self.assertEqual(text, "b\nc")

    def test_activity_log_markdown_wraps_recent_lines(self):
        text = format_activity_log_markdown(["old", "new"], title="초안 작성 로그", limit=1)
        self.assertIn("# 초안 작성 로그", text)
        self.assertIn("- 로그 줄 수: 1개", text)
        self.assertNotIn("old", text)
        self.assertIn("new", text)

    def test_intel_fig_returns_none_without_keywords(self):
        self.assertIsNone(build_intel_fig({}))

    def test_theme_returns_style_tag(self):
        css = launchpad_css()
        self.assertIn("<style>", css)
        self.assertIn("--gp-accent", css)

    def test_test_summary_includes_wave_and_script_count(self):
        summary = build_test_summary(
            [{"tone": "neutral", "title": "hello", "content": "world"}],
            {"sentiment": "neutral"},
            3,
        )
        self.assertIn("리허설 3회차", summary)
        self.assertIn("[원고]", summary)

    def test_ai_occupation_card_escapes_gallery(self):
        view = build_ai_occupation_view(
            [{"post_no": "1", "is_bot": True}],
            {"total_post_count": 1},
            set(),
        )
        html = render_ai_occupation_card("<gallery>", view)
        self.assertIn("&lt;gallery&gt;", html)
        self.assertIn("100.0%", html)

    def test_intel_briefing_card_escapes_content_and_has_meme_fallback(self):
        html = render_intel_briefing_card(
            gallery_id="g<script>",
            sentiment="긍정<script>",
            sentiment_class="intel-sentiment-friendly",
            hot_topics=["<hot>"],
            memes=[],
            top_keywords=["<kw>"],
            stats={"titles_count": 1, "comments_count": 2, "keywords_found": 3},
        )
        self.assertIn("g&lt;script&gt;", html)
        self.assertIn("&lt;hot&gt;", html)
        self.assertIn("&lt;kw&gt;", html)
        self.assertIn("감지된 밈 없음", html)
        self.assertNotIn("<script>", html)

    def test_compact_intel_escapes_and_limits_content(self):
        html = render_compact_intel(
            {
                "ai_analysis": "<analysis> " + ("long " * 80),
                "summary": "<summary>",
                "hot_topics": ["<hot>"],
                "top_keywords": ["<kw>"],
            },
            gallery_id="<gallery>",
            sentiment="<sentiment>",
        )
        self.assertIn("&lt;gallery&gt;", html)
        self.assertIn("&lt;sentiment&gt;", html)
        self.assertIn("&lt;hot&gt;", html)
        self.assertIn("&lt;kw&gt;", html)
        self.assertIn("…", html)
        self.assertNotIn("<analysis>", html)

    def test_compact_text_collapses_whitespace(self):
        self.assertEqual(compact_text("  a\n\n b\t c  "), "a b c")

    def test_normalize_ai_briefing_text_removes_placeholder_duplication(self):
        self.assertEqual(
            normalize_ai_briefing_text("특정 유저라는 특정 유저에 대한 말"),
            "특정 유저에 대한 말",
        )
        self.assertEqual(
            normalize_ai_briefing_text("특정 특정 유저 비판"),
            "특정 유저 비판",
        )

    def test_build_briefing_topic_allows_summary_only(self):
        text = build_briefing_topic({"summary": "요약만 있음"})
        self.assertEqual(text, "씨앗 떡밥: 요약만 있음")

    def test_build_briefing_topic_keeps_slot_warning_out(self):
        text = build_briefing_topic(
            {"ai_analysis": "분석", "generation_guidance": "지시", "summary": "요약"},
            slot_warning="overlap",
        )
        self.assertIn("분석", text)
        self.assertNotIn("[분위기 브리핑]", text)
        self.assertNotIn("[작문 지시]\n지시", text)
        self.assertIn("씨앗 떡밥: 요약", text)
        self.assertNotIn("슬롯 다양성", text)

    def test_build_generation_guidance_returns_separate_guidance(self):
        self.assertEqual(
            build_generation_guidance({"generation_guidance": " 지시 "}),
            "지시",
        )

    def test_parse_failure_has_no_generation_guidance_or_topic_seed(self):
        failed = {
            "_parse_error": True,
            "ai_analysis": "파싱 실패",
            "generation_guidance": "원본 로그 확인",
            "summary": "N/A",
            "style_profile": {"gallery_name": "우주갤", "rules": ["문체 지시"]},
        }

        self.assertEqual(build_generation_guidance(failed), "")
        self.assertFalse(has_briefing_topic_source(failed))

    def test_build_generation_guidance_appends_slot_warning(self):
        text = build_generation_guidance(
            {"generation_guidance": "지시"},
            slot_warning="overlap",
        )
        self.assertIn("지시", text)
        self.assertIn("슬롯 다양성 보정", text)

    def test_build_generation_guidance_appends_style_profile(self):
        text = build_generation_guidance(
            {
                "generation_guidance": "지시",
                "style_profile": {
                    "gallery_name": "야구갤",
                    "laugh_ratio": 0.4,
                    "long_laugh_ratio": 0.2,
                    "shortener_ratio": 0.1,
                    "avg_title_len": 18.0,
                    "rules": ["ㅋㅋㅋㅋ 정도를 가끔 허용한다."],
                },
            }
        )

        self.assertIn("지시", text)
        self.assertIn("갤러리별 문체 프로필", text)
        self.assertIn("야구갤", text)

    def test_format_intel_markdown_contains_copy_sections(self):
        text = format_intel_markdown(
            {
                "ai_analysis": "브리핑",
                "generation_guidance": "지시",
                "summary": "[A: 소재]",
                "hot_topics": ["핫토픽"],
                "memes": ["밈"],
                "top_keywords": ["키워드"],
                "stats": {"titles_count": 1, "comments_count": 2, "keywords_found": 3},
            },
            gallery_id="baseball_new13",
            sentiment="불만",
        )

        self.assertIn("# 분위기 브리핑", text)
        self.assertIn("- 게시판: `baseball_new13`", text)
        self.assertIn("## AI 브리핑\n브리핑", text)
        self.assertIn("## 작문 지시\n지시", text)
        self.assertIn("## 씨앗 떡밥\n[A: 소재]", text)

    def test_review_package_markdown_bundles_logs_briefing_and_scripts(self):
        text = format_review_package_markdown(
            intel_result={
                "ai_analysis": "브리핑",
                "generation_guidance": "지시",
                "summary": "[A: 소재]",
                "stats": {"titles_count": 1, "comments_count": 0, "keywords_found": 2},
                "raw_posts": [
                    {
                        "page": 1,
                        "post_no": "10",
                        "title": "원본 제목",
                        "content": "게시판 원본 본문",
                        "comments": ["원본 댓글"],
                    }
                ],
            },
            gallery_id="baseball_new13",
            sentiment="냉소",
            intel_logs=["읽기 로그"],
            draft_logs=["작성 로그"],
            scripts=[
                {
                    "wave": 2,
                    "persona_name": "혼잣말",
                    "tone": "monologue",
                    "title": "제목",
                    "content": "본문",
                }
            ],
        )

        self.assertIn("# Ghost Protocol 검토 패키지", text)
        self.assertIn("## 게시판 읽기 로그", text)
        self.assertIn("읽기 로그", text)
        self.assertIn("## 원본 게시글 자료", text)
        self.assertIn("### 원본 제목 리스트", text)
        self.assertIn("[p1 #10] 원본 제목", text)
        self.assertIn("### 원본 제목 + 본문 + 댓글 세트", text)
        self.assertIn("게시판 원본 본문", text)
        self.assertIn("원본 댓글", text)
        self.assertIn("# 분위기 브리핑", text)
        self.assertIn("## AI 브리핑\n브리핑", text)
        self.assertIn("## 초안 작성 로그", text)
        self.assertIn("작성 로그", text)
        self.assertIn("# 검토용 원고 모음", text)
        self.assertIn("## 원고 2", text)

    def test_format_actor_briefing_markdown_mentions_public_cluster_boundary(self):
        text = format_actor_briefing_markdown(
            {
                "summary": {
                    "actor_count": 1,
                    "major_actor_count": 1,
                    "resident_like_count": 0,
                    "skipped_comment_count": 2,
                },
                "actors": [
                    {
                        "display_label": "고닉 · fixed",
                        "post_count": 1,
                        "comment_count": 1,
                        "total_count": 2,
                        "top_terms": ["보드게임"],
                        "active_hours": ["20"],
                        "style": {
                            "avg_chars": 24,
                            "laugh_rate": 0,
                            "question_rate": 0.5,
                        },
                        "scores": {"resident_score": 0.3, "activity_score": 0.2},
                        "observations": [
                            {
                                "kind": "post",
                                "post_no": "1",
                                "title": "제목",
                                "excerpt": "본문",
                            }
                        ],
                    }
                ],
            }
        )

        self.assertIn("공개 닉네임/ID/IP 힌트", text)
        self.assertIn("작성자 정보 없는 댓글 2개", text)

    def test_review_package_markdown_includes_actor_briefing(self):
        text = format_review_package_markdown(
            intel_result={
                "actor_briefing": {
                    "summary": {
                        "actor_count": 1,
                        "major_actor_count": 1,
                        "resident_like_count": 1,
                        "skipped_comment_count": 0,
                    },
                    "actors": [
                        {
                            "display_label": "ㅇㅇ · 1.2",
                            "post_count": 2,
                            "comment_count": 0,
                            "total_count": 2,
                            "top_terms": ["목성"],
                            "style": {"avg_chars": 18.0},
                            "scores": {
                                "resident_score": 0.7,
                                "activity_score": 0.4,
                            },
                        }
                    ],
                }
            },
            gallery_id="universe",
        )

        self.assertIn("## 주요 액터 브리핑", text)
        self.assertIn("ㅇㅇ · 1.2", text)

    def test_has_briefing_topic_source_accepts_summary_only(self):
        self.assertTrue(has_briefing_topic_source({"summary": "요약"}))
        self.assertTrue(has_briefing_topic_source({"ai_analysis": "분석"}))
        self.assertTrue(has_briefing_topic_source({"generation_guidance": "지시"}))
        self.assertFalse(has_briefing_topic_source({"summary": "   "}))
        self.assertFalse(has_briefing_topic_source({}))

    def test_situation_summary_escapes_and_preserves_line_breaks(self):
        html = render_situation_summary("line1\n<script>", "analysis")
        self.assertIn("line1<br>&lt;script&gt;", html)
        self.assertIn("상황 요약", html)
        self.assertNotIn("<script>", html)

    def test_empty_situation_summary_returns_empty_string(self):
        self.assertEqual(render_situation_summary("", ""), "")

    def test_export_limit_caption_mentions_only_exceeded_limits(self):
        caption = format_export_limit_caption(
            post_count=120,
            comment_count=20,
            hard_limit=100,
        )
        self.assertIn("최대 100행", caption)
        self.assertIn("게시글 120행", caption)
        self.assertNotIn("댓글 20행 중", caption)

    def test_intel_log_panel_escapes_and_limits_lines(self):
        html = render_intel_log_panel(["old", "<new>", "last"], limit=2)
        self.assertNotIn("old", html)
        self.assertIn("&lt;new&gt;", html)
        self.assertNotIn("<new>", html)
        self.assertIn("last", html)

    def test_intel_empty_states_render_expected_copy(self):
        self.assertIn("분위기 읽는 중", render_intel_running_empty())
        self.assertIn("아직 읽은 분위기", render_intel_idle_empty())

    def test_swarm_preview_card_escapes_content(self):
        html = render_swarm_preview_card(
            title="<title>",
            content="<body>",
            wave_label='WAVE "1"',
        )
        self.assertIn("&lt;title&gt;", html)
        self.assertIn("&lt;body&gt;", html)
        self.assertIn("&quot;1&quot;", html)
        self.assertNotIn("<title>", html)

    def test_swarm_empty_preview_contains_prompt(self):
        self.assertIn("주제를 입력", render_swarm_empty_preview())

    def test_mission_stat_pill_escapes_value_label_and_class(self):
        html = render_mission_stat_pill(
            css_class='ms-ok" onclick="bad',
            value="<1>",
            label="<성공>",
        )
        self.assertIn("&lt;1&gt;", html)
        self.assertIn("&lt;성공&gt;", html)
        self.assertIn("&quot; onclick=&quot;bad", html)
        self.assertNotIn('onclick="bad', html)


    def test_build_generation_guidance_appends_composition_profile(self):
        text = build_generation_guidance(
            {
                "generation_guidance": "guide",
                "composition_profile": {
                    "sample_size": 3,
                    "shape": "title_driven",
                    "depth": "shallow",
                    "avg_title_len": 18.0,
                    "avg_body_len": 12.0,
                    "title_only_ratio": 0.67,
                    "body_present_ratio": 0.33,
                    "comment_presence_ratio": 0.0,
                    "rules": ["keep the body as one small aftertaste"],
                },
            }
        )

        self.assertIn("guide", text)
        self.assertIn("[Composition Profile]", text)
        self.assertIn("keep the body as one small aftertaste", text)


if __name__ == "__main__":
    unittest.main()
