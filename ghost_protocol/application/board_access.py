"""Budgeted, browser-backed read access for public board source material.

This module is deliberately the only read transport used by ``TrendScraper``.
It keeps login state out of collection, serializes requests across worker
threads, records compact diagnostics, and treats blank HTTP responses as a
hard stop instead of a retry signal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import random
import threading
import time
from typing import Protocol
from urllib.parse import urlsplit

from ghost_protocol.config import BLOCKED_STATUS_CODES, BLOCKED_TEXT_MARKERS, USER_AGENTS


@dataclass(frozen=True)
class BoardReadResponse:
    """Sanitized result of one browser-originated source request."""

    status: int
    body: str
    url: str
    error: str = ""
    blocked: bool = False
    reason: str = ""

    @property
    def byte_count(self) -> int:
        return len((self.body or "").encode("utf-8", errors="replace"))


class BoardReadTransport(Protocol):
    """Internal seam for browser transport and deterministic test fakes."""

    def get_html(self, url: str) -> BoardReadResponse: ...

    def post_form(
        self,
        url: str,
        payload: dict[str, str],
        headers: dict[str, str],
    ) -> BoardReadResponse: ...

    def close(self) -> None: ...


class PlaywrightBoardTransport:
    """Anonymous single-page Chromium transport.

    It never receives a saved poster session and it never attempts a login.
    The one page/context exists only for the lifetime of a source read unit.
    """

    def __init__(self, *, timeout_ms: int = 10_000) -> None:
        self._timeout_ms = max(1_000, int(timeout_ms))
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_page(self):
        if self._page is not None:
            return self._page

        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = self._context.new_page()

        def allow_only_explicit_source_requests(route) -> None:
            """Keep subresources out of an otherwise small, ledgered read unit.

            A list/detail response is parsed from its raw document body, so
            scripts, stylesheets, ads, fonts, and iframe documents add no
            collection value.  The only non-navigation request we need is the
            explicit comment ``fetch`` made by :meth:`post_form` below.
            """

            request = route.request
            is_main_document = (
                request.resource_type == "document"
                and request.is_navigation_request()
                and request.frame == page.main_frame
            )
            is_explicit_fetch = request.resource_type in {"fetch", "xhr"}
            if is_main_document or is_explicit_fetch:
                route.continue_()
            else:
                route.abort()

        page.route("**/*", allow_only_explicit_source_requests)
        self._page = page
        return page

    def get_html(self, url: str) -> BoardReadResponse:
        page = self._ensure_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            raw_body = response.text() if response else ""
            return BoardReadResponse(
                status=int(response.status) if response else 0,
                # ``page.content()`` fabricates an empty html/body shell even
                # for an empty HTTP 200.  Preserve the actual response body so
                # the guard can stop on the white-page condition.
                body=raw_body or "",
                url=page.url or url,
            )
        except Exception as exc:  # browser-specific errors become diagnostics at the guarded seam
            return BoardReadResponse(status=0, body="", url=url, error=str(exc)[:240])

    def post_form(
        self,
        url: str,
        payload: dict[str, str],
        headers: dict[str, str],
    ) -> BoardReadResponse:
        page = self._ensure_page()
        safe_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() not in {"referer", "user-agent", "cookie", "host", "content-length"}
        }
        try:
            result = page.evaluate(
                """async ({url, payload, headers}) => {
                    const response = await fetch(url, {
                        method: 'POST',
                        headers,
                        body: new URLSearchParams(payload).toString(),
                        credentials: 'same-origin',
                    });
                    return {
                        status: response.status,
                        body: await response.text(),
                        url: response.url,
                    };
                }""",
                {"url": url, "payload": payload, "headers": safe_headers},
            )
            return BoardReadResponse(
                status=int(result.get("status") or 0),
                body=str(result.get("body") or ""),
                url=str(result.get("url") or url),
            )
        except Exception as exc:  # browser-specific errors become diagnostics at the guarded seam
            return BoardReadResponse(status=0, body="", url=url, error=str(exc)[:240])

    def close(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._page = None
            try:
                if self._browser is not None:
                    self._browser.close()
            finally:
                self._browser = None
                if self._playwright is not None:
                    self._playwright.stop()
                self._playwright = None


class GuardedBoardAccess:
    """A deep source-read module: browser access, pacing, budget, and evidence.

    Callers only choose the request kind.  This module decides whether the
    request may leave the process, records its result, and permanently stops
    the read unit after a block-like result.
    """

    _global_lock = threading.Lock()
    _global_next_request_at = 0.0

    def __init__(
        self,
        *,
        transport: BoardReadTransport | None = None,
        purpose: str = "trend",
        request_budget: int = 20,
        min_interval_seconds: float = 1.2,
        ledger_path: Path | None = None,
    ) -> None:
        self._transport = transport or PlaywrightBoardTransport()
        self._purpose = str(purpose or "trend")[:48]
        self._request_budget = max(1, int(request_budget))
        self._min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._ledger_path = ledger_path or (
            Path(__file__).resolve().parents[2] / "logs" / "source_access.jsonl"
        )
        self._request_count = 0
        self._status = "ok"
        self._reason = ""
        self._events: list[dict[str, object]] = []
        self._closed = False

    @property
    def stopped(self) -> bool:
        return self._status != "ok"

    def _wait_for_global_slot(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        while True:
            with self._global_lock:
                now = time.monotonic()
                wait_seconds = self.__class__._global_next_request_at - now
                if wait_seconds <= 0:
                    self.__class__._global_next_request_at = now + self._min_interval_seconds
                    return
            time.sleep(wait_seconds)

    @staticmethod
    def _path_only(url: str) -> str:
        parsed = urlsplit(str(url or ""))
        return parsed.path or "/"

    def _append_event(
        self,
        *,
        method: str,
        kind: str,
        response: BoardReadResponse,
        reason: str = "",
        attempted: bool = True,
    ) -> None:
        event = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "purpose": self._purpose,
            "method": method,
            "kind": str(kind or "unknown"),
            "attempted": bool(attempted),
            "status": int(response.status or 0),
            "bytes": response.byte_count,
            "path": self._path_only(response.url),
            "reason": str(reason or response.reason or "")[:120],
        }
        self._events.append(event)
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            # Diagnostics must never break the stop gate itself.
            pass

    def stop(self, reason: str, *, kind: str = "guard") -> None:
        if self.stopped:
            return
        self._status = "blocked"
        self._reason = str(reason or "source_stopped")[:120]
        self._append_event(
            method="SKIP",
            kind=kind,
            response=BoardReadResponse(status=0, body="", url="", blocked=True, reason=self._reason),
            reason=self._reason,
            attempted=False,
        )

    def _classify(self, response: BoardReadResponse) -> str:
        if response.error:
            return "transport_error"
        if response.status in BLOCKED_STATUS_CODES:
            return f"http_{response.status}"
        if response.status < 200 or response.status >= 400:
            return f"http_{response.status or 0}"
        body = str(response.body or "")
        if not body.strip():
            return "empty_body"
        lowered = body.lower()
        if any(marker.lower() in lowered for marker in BLOCKED_TEXT_MARKERS):
            return "blocked_marker"
        return ""

    def _perform(
        self,
        method: str,
        url: str,
        *,
        kind: str,
        payload: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> BoardReadResponse:
        if self.stopped:
            return BoardReadResponse(status=0, body="", url=url, blocked=True, reason=self._reason)
        if self._request_count >= self._request_budget:
            self.stop("request_budget_exhausted", kind=kind)
            return BoardReadResponse(status=0, body="", url=url, blocked=True, reason=self._reason)

        self._wait_for_global_slot()
        self._request_count += 1
        try:
            if method == "GET":
                response = self._transport.get_html(url)
            else:
                response = self._transport.post_form(url, payload or {}, headers or {})
        except Exception as exc:  # a transport fault must still close the source read unit
            response = BoardReadResponse(
                status=0,
                body="",
                url=url,
                error=str(exc)[:240],
            )
        reason = self._classify(response)
        self._append_event(method=method, kind=kind, response=response, reason=reason)
        if reason:
            self._status = "blocked"
            self._reason = reason
            return replace(response, blocked=True, reason=reason)
        return response

    def get_html(self, url: str, *, kind: str) -> BoardReadResponse:
        return self._perform("GET", url, kind=kind)

    def post_form(
        self,
        url: str,
        payload: dict[str, str],
        headers: dict[str, str],
        *,
        kind: str,
    ) -> BoardReadResponse:
        return self._perform("POST", url, kind=kind, payload=payload, headers=headers)

    def report(self) -> dict[str, object]:
        return {
            "status": self._status,
            "reason": self._reason,
            "request_count": self._request_count,
            "request_budget": self._request_budget,
            "purpose": self._purpose,
            "events": [dict(event) for event in self._events],
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def __enter__(self) -> "GuardedBoardAccess":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
