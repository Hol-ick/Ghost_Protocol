from __future__ import annotations

from ghost_protocol.application.board_access import (
    BoardReadResponse,
    GuardedBoardAccess,
)


class _FakeTransport:
    def __init__(self, responses: list[BoardReadResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def get_html(self, url: str) -> BoardReadResponse:
        self.calls.append(("GET", url))
        return self.responses.pop(0)

    def post_form(self, url: str, payload: dict[str, str], headers: dict[str, str]) -> BoardReadResponse:
        self.calls.append(("POST", url))
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def test_blank_200_stops_access_and_records_single_network_event(tmp_path) -> None:
    transport = _FakeTransport([BoardReadResponse(status=200, body="", url="https://example.test/list")])
    access = GuardedBoardAccess(
        transport=transport,
        purpose="test",
        request_budget=3,
        min_interval_seconds=0,
        ledger_path=tmp_path / "source_access.jsonl",
    )

    response = access.get_html("https://example.test/list", kind="list")
    skipped = access.get_html("https://example.test/list?page=2", kind="list")

    assert response.blocked
    assert response.reason == "empty_body"
    assert skipped.blocked
    assert access.report()["status"] == "blocked"
    assert access.report()["reason"] == "empty_body"
    assert access.report()["request_count"] == 1
    assert transport.calls == [("GET", "https://example.test/list")]
    assert '"query"' not in (tmp_path / "source_access.jsonl").read_text(encoding="utf-8")


def test_request_budget_prevents_additional_transport_calls(tmp_path) -> None:
    transport = _FakeTransport(
        [
            BoardReadResponse(status=200, body="<html>ok</html>", url="https://example.test/one"),
            BoardReadResponse(status=200, body="<html>ok</html>", url="https://example.test/two"),
        ]
    )
    access = GuardedBoardAccess(
        transport=transport,
        purpose="test",
        request_budget=2,
        min_interval_seconds=0,
        ledger_path=tmp_path / "source_access.jsonl",
    )

    first = access.get_html("https://example.test/one", kind="list")
    second = access.get_html("https://example.test/two", kind="detail")
    third = access.get_html("https://example.test/three", kind="comment")

    assert not first.blocked
    assert not second.blocked
    assert third.blocked
    assert third.reason == "request_budget_exhausted"
    assert access.report()["request_count"] == 2
    assert len(transport.calls) == 2


def test_transport_exception_stops_access_and_preserves_diagnostic(tmp_path) -> None:
    class _FailingTransport(_FakeTransport):
        def __init__(self) -> None:
            super().__init__([])

        def get_html(self, url: str) -> BoardReadResponse:
            self.calls.append(("GET", url))
            raise RuntimeError("browser connection lost")

    transport = _FailingTransport()
    access = GuardedBoardAccess(
        transport=transport,
        purpose="test",
        min_interval_seconds=0,
        ledger_path=tmp_path / "source_access.jsonl",
    )

    response = access.get_html("https://example.test/list", kind="list")

    assert response.blocked
    assert response.reason == "transport_error"
    assert access.report()["reason"] == "transport_error"
    assert access.report()["request_count"] == 1
