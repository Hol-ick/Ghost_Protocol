from collections import Counter

from ghost_protocol.domain import conversation_planner


def test_plan_uses_multiple_roles_without_gallery_hardcoding():
    topic = "[A: ballot error] / [B: margin debt] / [C: basic income]"
    posts = [
        {"title": "lottery number talk again", "content": "small side topic"},
        {"title": "morning snack photo", "content": "low stakes detail"},
    ]

    plan = conversation_planner.build_conversation_plan(
        10,
        topic,
        gallery_id="unknown_gallery",
        source_posts=posts,
    )

    roles = [assignment["role"] for assignment in plan["assignments"]]
    assert "main_thread" in roles
    assert "side_thread" in roles
    assert "casual_detail" in roles
    assert "universe" not in conversation_planner.batch_prompt_block(plan).casefold()


def test_gallery_axis_is_inferred_not_forced():
    topic = "[A: ballot error] / [B: margin debt] / [C: basic income]"

    unknown = conversation_planner.build_conversation_plan(
        10,
        topic,
        gallery_id="unknown_gallery",
        source_posts=[],
    )
    inferred = conversation_planner.build_conversation_plan(
        10,
        topic,
        gallery_id="universe",
        source_posts=[],
    )

    assert "gallery_axis" not in [a["role"] for a in unknown["assignments"]]
    assert "gallery_axis" in [a["role"] for a in inferred["assignments"]]


def test_wave_prompt_has_stance_and_recent_titles():
    topic = "[A: ballot error] / [B: margin debt] / [C: basic income]"
    plan = conversation_planner.build_conversation_plan(
        5,
        topic,
        source_posts=[{"title": "side thread one", "content": ""}],
    )

    block = conversation_planner.wave_prompt_block(
        plan,
        2,
        slot="R",
        used_titles=["first accepted title", "second accepted title"],
    )

    assert "[This Wave Conversation Role]" in block
    assert "Stance lane:" in block
    assert "Existing slot from generator: R" in block
    assert "first accepted title" in block
    assert "second accepted title" in block


def test_role_quota_keeps_main_thread_below_half_when_side_topics_exist():
    topic = "[A: ballot error] / [B: margin debt] / [C: basic income]"
    posts = [
        {"title": "lottery number talk", "content": ""},
        {"title": "snack photo after lunch", "content": ""},
        {"title": "weather got weird", "content": ""},
    ]

    plan = conversation_planner.build_conversation_plan(10, topic, source_posts=posts)
    counts = Counter(a["role"] for a in plan["assignments"])

    assert counts["main_thread"] <= 5
    assert counts["side_thread"] >= 2
    assert len(plan["assignments"]) == 10


def test_rehearsal_plan_widens_source_and_gallery_roles():
    topic = "[A: ballot error] / [B: margin debt] / [C: basic income]"
    posts = [
        {"title": "외행성 사진 화질 좋아짐", "content": "작은 장면"},
        {"title": "간식 사진 올라옴", "content": "낮은 소재"},
        {"title": "점심 뭐 먹냐", "content": "생활 소재"},
    ]

    plan = conversation_planner.build_conversation_plan(
        10,
        topic,
        gallery_id="universe",
        source_posts=posts,
        rehearsal_mode=True,
    )
    counts = Counter(a["role"] for a in plan["assignments"])

    assert plan["rehearsal_mode"] is True
    assert counts["main_thread"] <= 3
    assert counts["side_thread"] >= 3
    assert counts["gallery_axis"] >= 2
