from ghost_protocol.application import ai_post_monitor
from ghost_protocol.application import operator_settings


def test_rejects_opaque_single_symbol_marker() -> None:
    assert operator_settings.normalize_public_ai_marker("※") == ""


def test_public_marker_normalizer_is_disabled() -> None:
    assert operator_settings.normalize_public_ai_marker("AI") == ""


def test_public_disclosure_uses_compact_default_marker() -> None:
    title, content = ai_post_monitor.apply_public_disclosure(
        "title",
        "body",
        enabled=True,
        marker="AI",
    )

    assert title == "title"
    assert content == "body"


def test_publish_interval_is_clamped() -> None:
    assert operator_settings.normalize_publish_interval_minutes(0) == 1
    assert operator_settings.normalize_publish_interval_minutes(999) == 180


def test_publish_settings_normalize_user_values() -> None:
    settings = operator_settings.build_publish_settings(
        {
            "publish_interval_minutes": "999",
            "ai_disclosure_enabled": False,
            "ai_disclosure_marker": "·",
            "ai_comment_watch_limit": "999",
        }
    )

    assert settings.publish_interval_minutes == 180
    assert settings.ai_disclosure_enabled is False
    assert settings.ai_disclosure_marker == ""
    assert settings.ai_comment_watch_limit == operator_settings.MAX_AI_COMMENT_WATCH_LIMIT
