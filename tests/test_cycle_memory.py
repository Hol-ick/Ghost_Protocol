from ghost_protocol import cycle_memory


def test_gallery_memory_keeps_topic_bans_isolated():
    root = cycle_memory._default()

    universe = cycle_memory.get_gallery_memory(root, "universe")
    baseball = cycle_memory.get_gallery_memory(root, "baseball_new13")

    for _ in range(cycle_memory.TOPIC_TTL_BAN):
        cycle_memory.update_topic_ttl(universe, ["평평지구 음모론"])

    assert cycle_memory.get_banned_topics(universe) == ["평평지구 음모론"]
    assert cycle_memory.get_banned_topics(baseball) == []
    assert "universe" in root["galleries"]
    assert "baseball_new13" in root["galleries"]


def test_gallery_memory_reuses_existing_scope():
    root = cycle_memory._default()
    first = cycle_memory.get_gallery_memory(root, "baseball_new13")
    first["cycle_count"] = 7

    second = cycle_memory.get_gallery_memory(root, "baseball_new13")

    assert second["cycle_count"] == 7
