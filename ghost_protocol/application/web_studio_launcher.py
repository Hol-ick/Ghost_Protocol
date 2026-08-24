"""Pure validation for the loopback Web Studio launcher."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LauncherCommand:
    host: str
    port: int
    target: str = "ghost_protocol.api.main:app"
    error: str | None = None

    @property
    def args(self) -> tuple[str, ...]:
        if self.error:
            return ()
        return (
            "-m",
            "uvicorn",
            self.target,
            "--host",
            self.host,
            "--port",
            str(self.port),
        )


def build_launcher_command(*, host: str = "127.0.0.1", port: int = 8000) -> LauncherCommand:
    """Build a safe Uvicorn command without touching running processes."""

    normalized_host = str(host or "").strip()
    if normalized_host not in {"127.0.0.1", "localhost", "::1"}:
        return LauncherCommand(normalized_host, int(port), error="loopback_only")
    try:
        normalized_port = int(port)
    except (TypeError, ValueError):
        return LauncherCommand(normalized_host, 0, error="invalid_port")
    if not 1 <= normalized_port <= 65535:
        return LauncherCommand(normalized_host, normalized_port, error="invalid_port")
    return LauncherCommand(normalized_host, normalized_port)


__all__ = ["LauncherCommand", "build_launcher_command"]
