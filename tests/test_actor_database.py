from __future__ import annotations

from ghost_protocol import database


def test_save_and_load_actor_briefing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(database, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "ghost.sqlite3"))

    database.init_db()
    briefing = {
        "summary": {"actor_count": 1, "major_actor_count": 1},
        "actors": [
            {
                "actor_key": "actor:abc",
                "display_label": "ㅇㅇ · 1.2",
                "identity_type": "ip",
                "post_count": 2,
                "comment_count": 1,
                "total_count": 3,
                "active_hours": ["12"],
                "top_terms": ["목성", "행성"],
                "style": {"avg_chars": 20.0},
                "scores": {"resident_score": 0.7, "activity_score": 0.5},
                "observations": [
                    {
                        "kind": "post",
                        "post_no": "10",
                        "title": "목성",
                        "excerpt": "목성 중력 얘기",
                        "created_at": "2026-06-01 12:00:00",
                    }
                ],
            }
        ],
    }

    database.save_actor_briefing("universe", briefing)

    loaded = database.get_actor_briefing("universe")
    profiles = database.get_actor_profiles("universe")

    assert loaded["summary"]["actor_count"] == 1
    assert profiles[0]["actor_key"] == "actor:abc"
    assert profiles[0]["top_terms"] == ["목성", "행성"]
    assert profiles[0]["style"]["avg_chars"] == 20.0
