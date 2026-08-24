from ghost_protocol.application.web_studio_launcher import build_launcher_command


def test_launcher_refuses_non_loopback_host() -> None:
    result = build_launcher_command(host="0.0.0.0")
    assert result.error == "loopback_only"
    assert result.args == ()


def test_launcher_builds_uvicorn_command_without_process_cleanup() -> None:
    result = build_launcher_command(host="127.0.0.1", port=8123)
    assert result.error is None
    assert result.args == (
        "-m",
        "uvicorn",
        "ghost_protocol.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8123",
    )


def test_launcher_rejects_invalid_port() -> None:
    assert build_launcher_command(port=0).error == "invalid_port"
    assert build_launcher_command(port=65536).error == "invalid_port"
