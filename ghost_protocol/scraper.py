"""Ghost Protocol v1.7 "Stealth Detect" - Parallel async DC Inside scraper.

v1.6 Changes:
  - Time-Based Crawling: 시간 범위 기반 수집 (페이지 수 대신 hours 지정)
  - Image URL Saver: <img src> 추출 + 저장 (base64 제외)
  - _parse_date(): DC Inside 날짜 포맷 통합 파서

Architecture (v1.6):
  DB ──→ collected_ids (Set) ──→ Dedup Filter
                                       ↓
  _parse_date() ──→ Time Cutoff ──→ Page Loop Break
                                       ↓
  BrowserContext (1) ─── 15 Workers ─── asyncio.gather()
                                       ↓
                         DB + CSV + JSONL (thread-safe)
"""

import asyncio
import json
import os
import random
import re
import sys
import time as _time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Awaitable

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

# ══════════════════════════════════════════════
# TrendScraper 경량 HTTP 의존성 (Playwright 불필요)
# ══════════════════════════════════════════════
try:
    import requests as _requests
    from bs4 import BeautifulSoup as _BeautifulSoup
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ══════════════════════════════════════════════
# PyInstaller 환경에서 Playwright 브라우저 경로 보정
# ══════════════════════════════════════════════
def _fix_playwright_path() -> None:
    if getattr(sys, 'frozen', False):
        default_path = Path.home() / "AppData" / "Local" / "ms-playwright"
        if default_path.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(default_path)


_fix_playwright_path()

from .config import (
    DATA_DIR,
    GALLERY_PATTERNS,
    POST_URL_PATTERNS,
    GALLERY_DETECT_URL,
    DC_MAIN_URL,
    USER_AGENTS,
    MIN_DELAY,
    MAX_DELAY,
    PAGE_DELAY_MIN,
    PAGE_DELAY_MAX,
    PARALLEL_WORKERS,
    PARALLEL_DELAY_MIN,
    PARALLEL_DELAY_MAX,
    BATCH_COOLDOWN_MIN,
    BATCH_COOLDOWN_MAX,
    PAGE_TIMEOUT,
    LIST_TIMEOUT,
    DETECT_TIMEOUT,
    BLOCKED_RESOURCE_TYPES,
    CIRCUIT_BREAKER_COOLDOWN,
    CIRCUIT_BREAKER_MAX_RETRIES,
    BLOCKED_STATUS_CODES,
    BLOCKED_TEXT_MARKERS,
    BOT_TIME_WINDOW_SEC,
    BOT_CPM_THRESHOLD,
    BOT_CLEANUP_INTERVAL,
    SUSPICIOUS_KEYWORDS,
    CLEAN_TEXT_PATTERNS,
)
from . import database
from .database import StreamWriter


# ══════════════════════════════════════════════
# Text preprocessing for LLM data
# ══════════════════════════════════════════════
_CLEAN_REGEXES = [re.compile(p) for p in CLEAN_TEXT_PATTERNS]


def clean_text(raw: str) -> str:
    """본문 텍스트 정제 — HTML 태그, dc앱 꼬리말, URL, 특수문자 제거."""
    text = raw
    for rx in _CLEAN_REGEXES:
        text = rx.sub("", text)
    # 연속 공백/줄바꿈 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_style_tags(title: str, content: str) -> str:
    """게시글 스타일 태그 추출 — LLM 학습용 메타데이터.

    Returns: comma-separated tags (e.g., "short_text,has_question,ends_with_lol")
    """
    tags = []
    combined = f"{title} {content}"

    if len(content) < 30:
        tags.append("short_text")
    elif len(content) > 500:
        tags.append("long_text")

    if any(c in combined for c in "?？"):
        tags.append("has_question")

    lol_endings = ["ㅋㅋ", "ㅎㅎ", "ㄷㄷ", "ㅠㅠ", "ㅜㅜ"]
    if any(content.rstrip().endswith(e) for e in lol_endings):
        tags.append("ends_with_lol")

    if re.search(r"[!！]{2,}", combined):
        tags.append("exclamation")

    if "http" in content.lower() or "www." in content.lower():
        tags.append("has_link")

    if re.search(r"\d{1,3}(,\d{3})+|\d+원|\$\d+", combined):
        tags.append("has_price")

    return ",".join(tags) if tags else ""


# ══════════════════════════════════════════════
# Date parsing for DC Inside
# ══════════════════════════════════════════════
def _parse_date(date_str: str) -> Optional[datetime]:
    """DC Inside 날짜 문자열 파싱.

    DC 날짜 포맷:
      - title 속성: "2025-02-13 14:30:22"  (full datetime)
      - 텍스트 표시:
        * 오늘: "14:30"  (HH:MM only)
        * 이전: "02.13"  (MM.DD only)
        * 작년이전: "2024.02.13" (YYYY.MM.DD)

    Returns: datetime or None (파싱 실패 시)
    """
    s = date_str.strip()
    if not s:
        return None

    now = datetime.now()

    # Format 1: "2025-02-13 14:30:22" (title 속성, full datetime)
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    # Format 2: "2025.02.13 14:30:22"
    try:
        return datetime.strptime(s, "%Y.%m.%d %H:%M:%S")
    except ValueError:
        pass

    # Format 3: "2025.02.13"
    try:
        return datetime.strptime(s, "%Y.%m.%d")
    except ValueError:
        pass

    # Format 4: "02.13" (MM.DD — 올해로 가정)
    m = re.match(r"^(\d{1,2})\.(\d{1,2})$", s)
    if m:
        try:
            return datetime(now.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    # Format 5: "14:30" (HH:MM — 오늘 날짜로 가정)
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        try:
            return datetime(now.year, now.month, now.day,
                            int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    return None


# ══════════════════════════════════════════════
# Image URL extraction
# ══════════════════════════════════════════════
_MAX_IMAGE_URL_LEN = 500  # base64 data URI 등 초장 URL 제외


def _extract_image_urls(html: str) -> list[str]:
    """<img> 태그에서 src URL 추출 — base64, 빈 값 제외."""
    if not html:
        return []
    urls = re.findall(r'<img\s[^>]*?src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    return [
        u for u in urls
        if u
        and not u.startswith("data:")
        and len(u) <= _MAX_IMAGE_URL_LEN
    ]


# ══════════════════════════════════════════════
# Custom exceptions
# ══════════════════════════════════════════════
class CrawlerBlockedError(Exception):
    """서버 차단 감지 (403, CAPTCHA 등)."""
    pass


# ══════════════════════════════════════════════
# Data structures
# ══════════════════════════════════════════════
@dataclass
class ScrapeResult:
    post_id: int = 0
    title: str = ""
    content: str = ""
    author: str = ""
    author_type: str = "유동닉"
    ip_hash: Optional[str] = None
    views: int = 0
    recommends: int = 0
    created_at: str = ""
    comments: list[dict] = field(default_factory=list)
    style_tags: str = ""
    has_image: bool = False
    is_winner: bool = False
    image_url: Optional[str] = None
    is_ai: bool = False


# Callback types
LogCallback = Callable[[str], Awaitable[None]]
ProgressCallback = Callable[[int, int], Awaitable[None]]
StatusCallback = Callable[[str, bool], Awaitable[None]]


class GalleryScraper:
    """DC Inside scraper v1.7 "Stealth Detect" — Parallel async engine."""

    def __init__(self, headless: bool = True):
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None       # 리스트 수집 전용
        self._playwright = None
        self._stop_flag = False
        self._headless = headless
        self.gallery_type: Optional[str] = None
        self.gallery_id: Optional[str] = None

        # ── Parallel control ──
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._write_lock = threading.Lock()  # DB/CSV 쓰기 동기화

        # ── Memory Dedup (v1.5) ──
        self._collected_ids: set[int] = set()  # DB에서 로딩된 기수집 post_id

        # ── Circuit Breaker ──
        self._block_count = 0

        # ── Bot Radar ──
        self._ip_activity_map: dict[str, list[float]] = defaultdict(list)
        self._total_checks: int = 0

        # ── RPS tracker ──
        self._request_timestamps: list[float] = []

        # ── Statistics ──
        self.stats_posts_scraped: int = 0
        self.stats_fixed_nick: int = 0
        self.stats_anon_nick: int = 0
        self.stats_bot_suspects: int = 0
        self.stats_comments_scraped: int = 0
        self.stats_skipped_dedup: int = 0  # v1.5: 중복 스킵 카운트

        # ── Stream Writer ──
        self._stream: Optional[StreamWriter] = None

    # ──────────────────────────────────────────
    # Browser lifecycle (Context Reuse)
    # ──────────────────────────────────────────
    async def start_browser(self) -> None:
        """브라우저 시작 — 헤드리스 탐지 우회 + Context 재사용."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        ua = random.choice(USER_AGENTS)
        self._context = await self._browser.new_context(
            user_agent=ua,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        # navigator.webdriver 속성 숨기기
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # 리스트 수집용 메인 페이지
        self._page = await self._context.new_page()
        await self._setup_resource_blocking(self._page)

    async def _setup_resource_blocking(self, page: Page) -> None:
        """리소스 차단 — 이미지, 폰트, CSS, 미디어 로딩 금지."""
        async def _block_resources(route):
            if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", _block_resources)

    async def _create_worker_page(self, worker_id: int) -> Page:
        """병렬 워커용 새 페이지 생성 — 탭마다 다른 UA."""
        ua = USER_AGENTS[worker_id % len(USER_AGENTS)]
        page = await self._context.new_page()
        # UA override (컨텍스트 전체 UA와 별도로 탭별 설정)
        await page.set_extra_http_headers({"User-Agent": ua})
        await self._setup_resource_blocking(page)
        return page

    async def close(self) -> None:
        if self._stream:
            self._stream.close()
            self._stream = None
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None

    def request_stop(self) -> None:
        self._stop_flag = True

    # ──────────────────────────────────────────
    # Circuit Breaker (Non-blocking)
    # ──────────────────────────────────────────
    async def _check_blocked(self, page: Page, status_code: int) -> None:
        if status_code in BLOCKED_STATUS_CODES:
            self._block_count += 1
            raise CrawlerBlockedError(f"HTTP {status_code}")
        try:
            body_text = await page.inner_text("body")
            body_lower = body_text.lower()
            for marker in BLOCKED_TEXT_MARKERS:
                if marker in body_lower:
                    self._block_count += 1
                    raise CrawlerBlockedError(f"Blocked text: '{marker}'")
        except CrawlerBlockedError:
            raise
        except Exception:
            pass

    async def _circuit_breaker_cooldown(
        self,
        log: Optional[LogCallback] = None,
        status_cb: Optional[StatusCallback] = None,
    ) -> bool:
        if self._block_count > CIRCUIT_BREAKER_MAX_RETRIES:
            if log:
                await log(
                    f"[CIRCUIT] Max retries ({CIRCUIT_BREAKER_MAX_RETRIES}) exceeded. FULL STOP."
                )
            if status_cb:
                await status_cb("CIRCUIT BREAKER - STOPPED", True)
            return False

        if log:
            await log(
                f"[CIRCUIT] BLOCK DETECTED - cooling down "
                f"(attempt {self._block_count}/{CIRCUIT_BREAKER_MAX_RETRIES})"
            )

        for remaining in range(CIRCUIT_BREAKER_COOLDOWN, 0, -1):
            if self._stop_flag:
                return False
            if status_cb:
                await status_cb(f"Cooling Down... ({remaining}s)", True)
            await asyncio.sleep(1)

        if log:
            await log("[CIRCUIT] Retrying with rotated User-Agent...")
        if status_cb:
            await status_cb("RETRYING...", False)
        return True

    # ──────────────────────────────────────────
    # Bot Radar (Time-Aware)
    # ──────────────────────────────────────────
    def _bot_radar_register(self, ip: Optional[str]) -> bool:
        if not ip:
            return False
        now = _time.time()
        self._ip_activity_map[ip].append(now)
        cutoff = now - BOT_TIME_WINDOW_SEC
        recent = [t for t in self._ip_activity_map[ip] if t >= cutoff]
        self._ip_activity_map[ip] = recent
        self._total_checks += 1
        if self._total_checks % BOT_CLEANUP_INTERVAL == 0:
            self._cleanup_old_timestamps(now)
        return len(recent) >= BOT_CPM_THRESHOLD

    def _cleanup_old_timestamps(self, now: float) -> None:
        cutoff = now - BOT_TIME_WINDOW_SEC
        empty_ips = []
        for ip, timestamps in self._ip_activity_map.items():
            filtered = [t for t in timestamps if t >= cutoff]
            if filtered:
                self._ip_activity_map[ip] = filtered
            else:
                empty_ips.append(ip)
        for ip in empty_ips:
            del self._ip_activity_map[ip]

    def _bot_radar_check_keywords(self, text: str) -> list[str]:
        if not text:
            return []
        return [kw for kw in SUSPICIOUS_KEYWORDS if kw in text]

    async def _bot_radar_report(
        self, post_id: int, author: str, ip: Optional[str],
        title: str, content: str,
        log: Optional[LogCallback] = None, worker_tag: str = "",
    ) -> None:
        if not log:
            return
        is_suspect_ip = self._bot_radar_register(ip)
        if is_suspect_ip:
            recent_count = len(self._ip_activity_map.get(ip, []))
            self.stats_bot_suspects += 1
            await log(
                f"{worker_tag}[BOT] High-freq IP #{post_id} | {author} ({ip}) "
                f"- {recent_count} posts in last {BOT_TIME_WINDOW_SEC}s"
            )
        matched_kw = self._bot_radar_check_keywords(f"{title} {content}")
        if matched_kw:
            kw_str = ", ".join(matched_kw)
            await log(f"{worker_tag}[BOT] Suspicious keywords #{post_id}: [{kw_str}]")

    # ──────────────────────────────────────────
    # RPS tracker
    # ──────────────────────────────────────────
    def _record_request(self) -> None:
        self._request_timestamps.append(_time.time())

    def get_rps(self) -> float:
        now = _time.time()
        self._request_timestamps = [
            t for t in self._request_timestamps if now - t <= 10.0
        ]
        if not self._request_timestamps:
            return 0.0
        elapsed = now - self._request_timestamps[0]
        if elapsed <= 0:
            return 0.0
        return len(self._request_timestamps) / elapsed

    # ──────────────────────────────────────────
    # Gallery detection (v1.7 — Smart Redirect)
    # ──────────────────────────────────────────
    async def detect_gallery_type(
        self, gallery_id: str, log: Optional[LogCallback] = None
    ) -> Optional[str]:
        """Playwright 기반 갤러리 타입 감지 — 1회 접속 + 리다이렉트 URL 분석.

        DC Inside는 메이저 갤러리 URL로 접속하면 실제 갤러리 타입에 맞게
        자동 리다이렉트한다. 최종 URL의 경로를 분석해서 타입을 판별:
          - /mgallery/ 포함 → 'mgallery' (마이너)
          - /mini/     포함 → 'mini'     (미니)
          - /board/    + 정상 → 'board'   (메이저)
          - 메인 페이지 / 에러 → None
        """
        self.gallery_id = gallery_id
        detect_url = GALLERY_DETECT_URL.format(gallery_id=gallery_id)

        if log:
            await log(f"[DETECT] Smart Redirect — {detect_url}")

        try:
            resp = await self._page.goto(
                detect_url,
                wait_until="domcontentloaded",
                timeout=DETECT_TIMEOUT,
            )
            self._record_request()

            final_url = self._page.url

            if log:
                await log(f"[DETECT] Redirect → {final_url}")

            # ── 메인 페이지로 튕김 = 갤러리 없음 ──
            if final_url.rstrip("/") == DC_MAIN_URL.rstrip("/"):
                if log:
                    await log(f"[FAIL] Redirected to DC main — gallery not found: {gallery_id}")
                return None

            # ── HTTP 에러 (403, 404 등) ──
            if resp and resp.status >= 400:
                if log:
                    await log(f"[FAIL] HTTP {resp.status} — gallery not found: {gallery_id}")
                return None

            # ── URL 경로로 갤러리 타입 판별 ──
            if "/mgallery/" in final_url:
                gtype = "mgallery"
            elif "/mini/" in final_url:
                gtype = "mini"
            elif "/board/" in final_url:
                # 메이저 갤러리 — 에러 페이지가 아닌지 추가 확인
                has_list = await self._page.query_selector(".gall_list")
                if not has_list:
                    if log:
                        await log(f"[FAIL] /board/ but no gallery list — error page: {gallery_id}")
                    return None
                gtype = "board"
            else:
                if log:
                    await log(f"[FAIL] Unknown redirect path: {final_url}")
                return None

            self.gallery_type = gtype
            if log:
                await log(f"[OK] {gtype} gallery detected: {gallery_id}")
            return gtype

        except Exception as e:
            if log:
                await log(f"[FAIL] Gallery detection error: {str(e)[:80]}")
            return None

    # ──────────────────────────────────────────
    # Debug: HTML Snapshot
    # ──────────────────────────────────────────
    async def _save_debug_snapshot(
        self, page: Page, prefix: str, log: Optional[LogCallback] = None,
    ) -> Optional[str]:
        """디버그용 HTML 스냅샷 저장 — data/debug/ 폴더."""
        try:
            debug_dir = os.path.join(DATA_DIR, "debug")
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = os.path.join(debug_dir, f"{prefix}_{ts}.html")
            html_content = await page.content()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(html_content)
            if log:
                await log(f"[DEBUG] HTML snapshot saved: {filepath}")
            return filepath
        except Exception as e:
            if log:
                await log(f"[DEBUG] Snapshot save failed: {str(e)[:60]}")
            return None

    # ──────────────────────────────────────────
    # Post list scraping (Sequential, uses main page)
    # ──────────────────────────────────────────
    async def scrape_post_list(
        self, page_num: int = 1, log: Optional[LogCallback] = None
    ) -> list[dict]:
        if not self.gallery_type or not self.gallery_id:
            return []
        base = GALLERY_PATTERNS[self.gallery_type].format(gallery_id=self.gallery_id)
        url = f"{base}&page={page_num}"
        if log:
            await log(f"[LIST] Page {page_num} collecting... {url}")

        page_start = _time.time()
        resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=LIST_TIMEOUT)
        self._record_request()
        page_load_time = _time.time() - page_start

        # ── Detailed Network Logging + Latency ──
        status_code = resp.status if resp else 0
        if log:
            page_title = await self._page.title()
            await log(
                f"[NET] HTTP {status_code} | Title: \"{page_title[:60]}\" | "
                f"URL: {self._page.url[:80]}"
            )
            await log(f"[PERF] Page {page_num} loaded in {page_load_time:.1f}s")

        if status_code != 200:
            if log:
                await log(f"[NET] ⚠️ Non-200 response ({status_code}) — skipping page {page_num}")
            await self._save_debug_snapshot(self._page, f"http{status_code}_page{page_num}", log)
            if status_code in BLOCKED_STATUS_CODES:
                await self._check_blocked(self._page, status_code)
            return []

        await asyncio.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        # ── Selector Validation ──
        rows = await self._page.query_selector_all("tr.ub-content.us-post")

        if not rows:
            if log:
                await log(f"[LIST] ⚠️ 0 rows found with 'tr.ub-content.us-post' selector!")

            # body 텍스트 앞 200자 출력 (차단 여부 텍스트 확인)
            try:
                body_text = await self._page.inner_text("body")
                preview = body_text.strip()[:200].replace("\n", " ")
                if log:
                    await log(f"[DEBUG] Body preview: \"{preview}\"")
            except Exception:
                if log:
                    await log("[DEBUG] Body text extraction failed")

            # HTML 스냅샷 저장
            await self._save_debug_snapshot(self._page, f"zero_rows_page{page_num}", log)
            return []

        if log:
            await log(f"[LIST] Parsing start... ({len(rows)} rows)")

        posts = []
        notice_count = 0
        for row in rows:
            try:
                # ── 1. 글 번호 확인 ──
                num_el = await row.query_selector(".gall_num")
                num_text = (await num_el.inner_text()).strip() if num_el else ""

                # ── 2. 공지사항 스킵 (날짜 확인 안 함, 절대 break 금지) ──
                if not num_text.isdigit():
                    notice_count += 1
                    continue

                # 추가 공지 감지: CSS 클래스에 'notice' 포함
                row_class = await row.get_attribute("class") or ""
                if "notice" in row_class.lower():
                    notice_count += 1
                    continue

                title_el = await row.query_selector(".gall_tit a")
                title = (await title_el.inner_text()).strip() if title_el else ""
                href = await title_el.get_attribute("href") if title_el else ""

                writer_el = await row.query_selector(".gall_writer")
                author, author_type, ip_hash = "", "유동닉", None
                if writer_el:
                    nick_el = await writer_el.query_selector(".nickname")
                    if nick_el:
                        author = (await nick_el.inner_text()).strip()
                    ip_el = await writer_el.query_selector(".ip")
                    if ip_el:
                        ip_hash = (await ip_el.inner_text()).strip()
                    data_uid = await writer_el.get_attribute("data-uid")
                    if data_uid and data_uid != "0":
                        author_type = "고정닉"

                count_el = await row.query_selector(".gall_count")
                views = 0
                if count_el:
                    v = (await count_el.inner_text()).strip()
                    views = int(v) if v.isdigit() else 0

                recommend_el = await row.query_selector(".gall_recommend")
                recommends = 0
                if recommend_el:
                    r = (await recommend_el.inner_text()).strip()
                    recommends = int(r) if r.lstrip("-").isdigit() else 0

                # ── 3. 날짜 파싱: title 속성 우선 (초 단위 정밀 시간) ──
                date_el = await row.query_selector(".gall_date")
                created_at = ""
                if date_el:
                    # title 속성에 "2026-02-14 12:10:22" 형식 정밀 시간
                    created_at = (await date_el.get_attribute("title")) or ""
                    if not created_at:
                        created_at = (await date_el.inner_text()).strip()

                posts.append({
                    "post_id": int(num_text),
                    "title": title,
                    "author": author,
                    "author_type": author_type,
                    "ip_hash": ip_hash,
                    "views": views,
                    "recommends": recommends,
                    "created_at": created_at,
                    "href": href,
                })
            except Exception:
                continue

        if log:
            skip_info = f" (notices skipped: {notice_count})" if notice_count else ""
            await log(
                f"[LIST] Parsing end — Page {page_num}: {len(posts)} posts found "
                f"(from {len(rows)} rows){skip_info}"
            )

        # 파싱 후에도 0건이면 스냅샷
        if not posts and rows:
            if log:
                await log(f"[LIST] ⚠️ {len(rows)} rows found but 0 valid posts — parsing issue?")
            await self._save_debug_snapshot(self._page, f"parse_fail_page{page_num}", log)

        return posts

    # ──────────────────────────────────────────
    # Parallel post detail scraping (NEW in v1.0)
    # ──────────────────────────────────────────
    async def _scrape_single_post(
        self,
        post_meta: dict,
        worker_id: int,
        log: Optional[LogCallback] = None,
    ) -> Optional[ScrapeResult]:
        """단일 게시글 상세 수집 — 개별 탭(Page)에서 실행.

        Semaphore로 동시 실행 수 제한.
        """
        worker_tag = f"[W{worker_id}] "
        post_id = post_meta["post_id"]
        result = ScrapeResult(post_id=post_id)

        async with self._semaphore:
            if self._stop_flag:
                return None

            page = await self._create_worker_page(worker_id)
            try:
                url_pattern = POST_URL_PATTERNS[self.gallery_type]
                url = url_pattern.format(gallery_id=self.gallery_id, post_id=post_id)

                # 랜덤 딜레이 (워커별 분산)
                await asyncio.sleep(random.uniform(PARALLEL_DELAY_MIN, PARALLEL_DELAY_MAX))

                resp = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
                self._record_request()
                await self._check_blocked(page, resp.status if resp else 0)

                # ── 본문 수집 ──
                title_el = await page.query_selector(".title_subject")
                if title_el:
                    result.title = (await title_el.inner_text()).strip()

                content_el = await page.query_selector(".write_div")
                if content_el:
                    result.content = (await content_el.inner_text()).strip()

                writer_el = await page.query_selector(".gall_writer")
                if writer_el:
                    nick_el = await writer_el.query_selector(".nickname")
                    if nick_el:
                        result.author = (await nick_el.inner_text()).strip()
                    ip_el = await writer_el.query_selector(".ip")
                    if ip_el:
                        result.ip_hash = (await ip_el.inner_text()).strip()
                    data_uid = await writer_el.get_attribute("data-uid")
                    if data_uid and data_uid != "0":
                        result.author_type = "고정닉"

                count_el = await page.query_selector(".gall_count")
                if count_el:
                    v = (await count_el.inner_text()).strip()
                    nums = re.findall(r"\d+", v)
                    if nums:
                        result.views = int(nums[0])

                rec_el = await page.query_selector(".gall_reply_num")
                if rec_el:
                    r = (await rec_el.inner_text()).strip()
                    nums = re.findall(r"-?\d+", r)
                    if nums:
                        result.recommends = int(nums[0])

                date_el = await page.query_selector(".fl .gall_date")
                if date_el:
                    result.created_at = (await date_el.get_attribute("title")) or (
                        await date_el.inner_text()
                    ).strip()

                # ── 댓글 수집 ──
                comment_els = await page.query_selector_all(".cmt_info")
                for cel in comment_els:
                    try:
                        c_author_el = await cel.query_selector(".gall_writer .nickname")
                        c_author = (await c_author_el.inner_text()).strip() if c_author_el else ""
                        c_content_el = await cel.query_selector(".usertxt")
                        c_content = (await c_content_el.inner_text()).strip() if c_content_el else ""
                        c_date_el = await cel.query_selector(".date_time")
                        c_date = (await c_date_el.inner_text()).strip() if c_date_el else ""
                        parent = await cel.evaluate_handle("el => el.closest('.reply_info')")
                        is_reply = 1 if parent else 0
                        result.comments.append({
                            "post_id": post_id,
                            "gallery_id": self.gallery_id,
                            "author": c_author,
                            "content": c_content,
                            "is_reply": is_reply,
                            "created_at": c_date,
                        })
                    except Exception:
                        continue

                # ── Image detection + URL extraction (before clean_text strips HTML) ──
                content_el_html = await content_el.inner_html() if content_el else ""
                result.has_image = bool(re.search(r"<img\s", content_el_html, re.IGNORECASE))
                if result.has_image:
                    img_urls = _extract_image_urls(content_el_html)
                    result.image_url = img_urls[0] if img_urls else None

                # ── High-Quality Tagging (념글 판별) ──
                result.is_winner = result.recommends >= 10

                # ── Zero-Width Watermark Detection (Ghost Protocol AI 탐지) ──
                _zwsp = "\u200B"
                result.is_ai = (
                    _zwsp in (result.title or "")
                    or _zwsp in (result.content or "")
                )

                # ── Style tags + Clean text ──
                result.style_tags = extract_style_tags(result.title, result.content)
                result.content = clean_text(result.content)

                # ── Statistics (thread-safe) ──
                self.stats_posts_scraped += 1
                self.stats_comments_scraped += len(result.comments)
                if result.author_type == "고정닉":
                    self.stats_fixed_nick += 1
                else:
                    self.stats_anon_nick += 1

                # ── Bot Radar ──
                await self._bot_radar_report(
                    post_id, result.author, result.ip_hash,
                    result.title, result.content, log, worker_tag,
                )

                if log:
                    title_preview = result.title[:25] + "..." if len(result.title) > 25 else result.title
                    win = "W" if result.is_winner else "-"
                    img = "I" if result.has_image else "-"
                    await log(
                        f'{worker_tag}[POST] #{post_id} [{win}{img}] "{title_preview}" | '
                        f"comments {len(result.comments)} | tags [{result.style_tags}]"
                    )

                return result

            except CrawlerBlockedError:
                raise
            except Exception as e:
                if log:
                    await log(f"{worker_tag}[ERR] #{post_id} failed: {str(e)[:60]}")
                return result
            finally:
                await page.close()

    # ──────────────────────────────────────────
    # Save result (thread-safe)
    # ──────────────────────────────────────────
    def _save_result(
        self, result: ScrapeResult, post_meta: dict, gallery_id: str
    ) -> None:
        """DB + CSV + JSONL 즉시 저장 — write_lock으로 동시성 보호."""
        title = result.title or post_meta.get("title", "")
        author = result.author or post_meta.get("author", "")
        author_type = result.author_type or post_meta.get("author_type", "유동닉")
        ip_hash = result.ip_hash or post_meta.get("ip_hash")
        views = result.views or post_meta.get("views", 0)
        recommends = result.recommends or post_meta.get("recommends", 0)
        created_at = result.created_at or post_meta.get("created_at", "")

        with self._write_lock:
            # SQLite
            database.insert_post(
                post_id=post_meta["post_id"],
                gallery_id=gallery_id,
                title=title,
                content=result.content,
                author=author,
                author_type=author_type,
                ip_hash=ip_hash,
                views=views,
                recommends=recommends,
                created_at=created_at,
                style_tags=result.style_tags,
                has_image=result.has_image,
                is_winner=result.is_winner,
                image_url=result.image_url,
                is_ai=getattr(result, "is_ai", False),
            )
            if result.comments:
                database.insert_comments(result.comments)

            # CSV Stream
            self._stream.write_post(
                post_id=post_meta["post_id"],
                gallery_id=gallery_id,
                title=title,
                content=result.content,
                author=author,
                author_type=author_type,
                ip_hash=ip_hash,
                views=views,
                recommends=recommends,
                created_at=created_at,
                style_tags=result.style_tags,
                has_image=result.has_image,
                is_winner=result.is_winner,
                image_url=result.image_url,
            )
            if result.comments:
                self._stream.write_comments(result.comments)

            # JSONL Stream (Instruction Tuning format)
            self._stream.write_jsonl(
                title=title,
                content=result.content,
                comments=result.comments,
                is_winner=result.is_winner,
                has_image=result.has_image,
                style_tags=result.style_tags,
                post_id=post_meta["post_id"],
                gallery_id=gallery_id,
                image_url=result.image_url,
            )

    # ──────────────────────────────────────────
    # Full pipeline v1.0 (Parallel)
    # ──────────────────────────────────────────
    async def run_full_scrape(
        self,
        gallery_id: str,
        num_pages: int = 1,
        time_limit_hours: float = 0,
        log: Optional[LogCallback] = None,
        progress: Optional[ProgressCallback] = None,
        status_cb: Optional[StatusCallback] = None,
        gallery_type: Optional[str] = None,
    ) -> int:
        """v1.6 파이프라인 — 시간 기반 수집 + Memory Dedup.

        Phase 0: DB에서 기수집 post_id 로딩 (중복 방지)
        Phase 1: 글 목록 수집 (Sequential, time cutoff 또는 page limit)
        Phase 2: 글 상세 수집 (Parallel, asyncio.gather + Semaphore)

        Args:
            time_limit_hours: >0이면 시간 기반 수집 (페이지 무제한, 날짜 초과 시 중단)
                              0이면 기존 num_pages 기반 수집
            gallery_type: 'board' / 'mgallery' / 'mini' 명시 시 자동 탐지 스킵
                          None이면 Playwright redirect 분석으로 자동 탐지
        """
        self._stop_flag = False
        self._block_count = 0
        self.stats_posts_scraped = 0
        self.stats_fixed_nick = 0
        self.stats_anon_nick = 0
        self.stats_bot_suspects = 0
        self.stats_comments_scraped = 0
        self.stats_skipped_dedup = 0
        self._ip_activity_map.clear()
        self._total_checks = 0
        self._request_timestamps.clear()
        total_saved = 0

        # Time-based mode
        use_time_mode = time_limit_hours > 0
        time_cutoff = datetime.now() - timedelta(hours=time_limit_hours) if use_time_mode else None

        self._semaphore = asyncio.Semaphore(PARALLEL_WORKERS)

        await self.start_browser()

        self._stream = StreamWriter(gallery_id)
        self._stream.open()

        try:
            if log:
                await log("> GHOST PROTOCOL v1.7 'STEALTH DETECT'")
                time_mins = int(time_limit_hours * 60)
                mode_str = f"Time-based: last {time_mins}min ({time_limit_hours:.2f}h)" if use_time_mode else f"Page-based: {num_pages} pages"
                await log(f"> Mode: {mode_str} | Workers: {PARALLEL_WORKERS}")
                await log(f"> Stream save: {self._stream.posts_path}")

            # gallery_type이 UI에서 명시 지정된 경우 자동 탐지 스킵
            if gallery_type and gallery_type in ("board", "mgallery", "mini"):
                gtype = gallery_type
                self.gallery_type = gtype
                self.gallery_id = gallery_id
                if log:
                    await log(f"[DETECT] 수동 지정 타입: {gtype} (자동 탐지 스킵)")
            else:
                gtype = await self.detect_gallery_type(gallery_id, log)
                if not gtype:
                    return 0

            database.init_db()

            # ── Phase 0: Memory Dedup — 기수집 ID 로딩 ──
            self._collected_ids = database.get_all_post_ids(gallery_id)
            if log:
                await log(f"[DEDUP] Loaded {len(self._collected_ids)} existing post IDs from DB")

            # ── Phase 1: 글 목록 수집 (Sequential, time-aware) ──
            if log:
                if use_time_mode:
                    await log(f"[PHASE 1] Time-based collection (cutoff: {time_cutoff.strftime('%Y-%m-%d %H:%M')})...")
                else:
                    await log(f"[PHASE 1] Collecting post lists ({num_pages} pages)...")
            if status_cb:
                await status_cb("Phase 1: Collecting post lists...", False)

            all_posts = []
            page_idx = 1
            max_pages = 200 if use_time_mode else num_pages  # time 모드: 최대 200페이지
            hit_time_limit = False

            while page_idx <= max_pages:
                if self._stop_flag:
                    if log:
                        await log("[STOP] User requested stop")
                    break
                try:
                    page_posts = await self.scrape_post_list(page_idx, log)

                    # ── Time cutoff 체크 (Sticky Post Immunity 적용) ──
                    # DC Inside 상단 ~10개 행은 고정 공지(Sticky)가 위치.
                    # 숫자 ID를 가진 고정글이 오래된 날짜를 가져도 break 금지.
                    # idx >= STICKY_IMMUNITY_ROWS 이후에만 cutoff break 허용.
                    STICKY_IMMUNITY_ROWS = 10

                    if use_time_mode and page_posts:
                        filtered = []
                        for idx, p in enumerate(page_posts):
                            post_dt = _parse_date(p.get("created_at", ""))

                            # 날짜 파싱 실패 → 그냥 포함 (break 금지)
                            if not post_dt:
                                filtered.append(p)
                                continue

                            # 시간 초과 감지
                            if time_cutoff and post_dt < time_cutoff:
                                # 상단 면책권: 상위 N개 행은 고정 공지로 간주
                                if idx < STICKY_IMMUNITY_ROWS:
                                    if log:
                                        await log(
                                            f"[SKIP] Sticky post at row {idx}: "
                                            f"#{p.get('post_id')} date={p.get('created_at')} "
                                            f"— immune (top {STICKY_IMMUNITY_ROWS} rows)"
                                        )
                                    continue  # break 절대 금지, 수집도 안 함

                                # 면책권 밖: 진짜 과거 글 → cutoff break
                                if log:
                                    await log(
                                        f"[TIME] Cutoff reached at row {idx}: "
                                        f"post #{p.get('post_id')} "
                                        f"date={p.get('created_at')} < "
                                        f"{time_cutoff.strftime('%Y-%m-%d %H:%M')}"
                                    )
                                hit_time_limit = True
                                break

                            filtered.append(p)

                        all_posts.extend(filtered)
                        if hit_time_limit:
                            if log:
                                await log(
                                    f"[TIME] Reached time limit at page {page_idx} "
                                    f"({time_limit_hours}h cutoff) — "
                                    f"collected {len(all_posts)} posts so far"
                                )
                            break
                    else:
                        # ── 증분 수집 (Incremental): 기수집 글 만나면 break ──
                        incremental_break = False
                        for p in page_posts:
                            if p["post_id"] in self._collected_ids:
                                if log:
                                    await log(
                                        f"[INCR] Already collected post #{p['post_id']} "
                                        f"— stopping list collection (incremental mode)"
                                    )
                                incremental_break = True
                                break
                            all_posts.append(p)
                        if incremental_break:
                            break

                    self._block_count = 0
                    page_idx += 1
                    await asyncio.sleep(random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX))
                except CrawlerBlockedError as e:
                    if log:
                        await log(f"[BLOCK] {e}")
                    can_retry = await self._circuit_breaker_cooldown(log, status_cb)
                    if not can_retry:
                        break

            if not all_posts:
                if log:
                    await log("[WARN] No posts found.")
                return 0

            # ── Dedup Filter: 기수집 글 제거 ──
            before_dedup = len(all_posts)
            all_posts = [
                p for p in all_posts if p["post_id"] not in self._collected_ids
            ]
            self.stats_skipped_dedup = before_dedup - len(all_posts)
            if log:
                await log(
                    f"[DEDUP] {before_dedup} total → {len(all_posts)} new "
                    f"({self.stats_skipped_dedup} duplicates skipped)"
                )

            if not all_posts:
                if log:
                    await log("[DONE] All posts already collected. Nothing to do.")
                return 0

            if log:
                await log(
                    f"[PHASE 2] Parallel scraping {len(all_posts)} posts "
                    f"with {PARALLEL_WORKERS} workers..."
                )
            if status_cb:
                await status_cb(f"Phase 2: Scraping {len(all_posts)} posts...", False)

            # ── Phase 2: 병렬 상세 수집 (Batch + Semaphore) ──
            batch_size = PARALLEL_WORKERS * 2  # 배치 크기 = 워커 수 * 2
            completed = 0

            for batch_start in range(0, len(all_posts), batch_size):
                if self._stop_flag:
                    if log:
                        await log("[STOP] User requested stop")
                    break

                batch = all_posts[batch_start:batch_start + batch_size]

                # asyncio.gather로 배치 내 병렬 실행
                tasks = []
                for i, post_meta in enumerate(batch):
                    worker_id = i % PARALLEL_WORKERS
                    task = self._scrape_single_post(post_meta, worker_id, log)
                    tasks.append(task)

                try:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                except Exception as e:
                    if log:
                        await log(f"[ERR] Batch error: {str(e)[:80]}")
                    results = []

                # 결과 저장
                for i, result in enumerate(results):
                    if isinstance(result, CrawlerBlockedError):
                        if log:
                            await log(f"[BLOCK] {result}")
                        can_retry = await self._circuit_breaker_cooldown(log, status_cb)
                        if not can_retry:
                            self._stop_flag = True
                            break
                        continue
                    if isinstance(result, Exception):
                        if log:
                            await log(f"[ERR] Task exception: {str(result)[:60]}")
                        continue
                    if result is None:
                        continue

                    post_meta = batch[i]
                    self._save_result(result, post_meta, gallery_id)
                    self._collected_ids.add(post_meta["post_id"])
                    total_saved += 1

                completed += len(batch)
                if progress:
                    await progress(min(completed, len(all_posts)), len(all_posts))

                # 10개 단위 진행 상황 로그
                if log and total_saved > 0 and total_saved % 10 < len(batch):
                    await log(
                        f"[PROGRESS] Scraped {total_saved}/{len(all_posts)} posts "
                        f"({total_saved * 100 // len(all_posts)}%)"
                    )

                # 배치 간 쿨다운
                if batch_start + batch_size < len(all_posts) and not self._stop_flag:
                    await asyncio.sleep(random.uniform(BATCH_COOLDOWN_MIN, BATCH_COOLDOWN_MAX))

            if log:
                mode_info = f"Time: {time_limit_hours}h" if use_time_mode else f"Pages: {num_pages}"
                await log(
                    f"[DONE] Scraping complete ({mode_info}): {total_saved} posts saved | "
                    f"Skipped(dedup): {self.stats_skipped_dedup} | "
                    f"Comments: {self.stats_comments_scraped} | "
                    f"Bot suspects: {self.stats_bot_suspects}"
                )
                await log(
                    f"[DONE] Stream: {self._stream.rows_written} CSV rows | "
                    f"JSONL: {self._stream.jsonl_path}"
                )
        finally:
            await self.close()

        return total_saved


# ══════════════════════════════════════════════════════════════════════════════
# TrendScraper — AJAX 기반 경량 Read-Only 트렌드 수집기 (v1.0)
#
# Architecture:
#   requests.Session ──→ 목록 페이지 HTML (BeautifulSoup 파싱)
#                    ──→ AJAX 댓글 API (POST /board/comment/ → JSON)
#   collect_trending() ─ 위 두 메서드 조합, progress_callback 지원
#
# Playwright 없이 동작 — 가볍고 빠름, 차단 위험↓
# ══════════════════════════════════════════════════════════════════════════════

class TrendScraper:
    """DC Inside 경량 Read-Only 트렌드 수집기.

    Playwright 없이 requests + BeautifulSoup으로 목록 페이지를 파싱하고,
    댓글은 DC Inside 내부 AJAX API를 직접 호출하여 수집한다.

    Usage:
        scraper = TrendScraper()
        data = scraper.collect_trending("baseball_new9", gallery_type="mgallery", pages=3)
        # → {"titles": [...], "comments": [...], "gallery_id": "...", ...}
    """

    # DC Inside 타입별 댓글 AJAX 엔드포인트
    _COMMENT_APIS: dict[str, str] = {
        "board":    "https://gall.dcinside.com/board/comment/",
        "mgallery": "https://gall.dcinside.com/mgallery/board/comment/",
        "mini":     "https://gall.dcinside.com/mini/board/comment/",
    }

    # HTML 태그 / DC 앱 워터마크 제거 패턴
    _CLEAN_RE = re.compile(
        r"<[^>]+>"                    # HTML 태그
        r"|https?://\S+"              # URL
        r"|- dc official App|- dc App"  # DC 앱 워터마크
        r"|\[.*?\]"                   # [이미지], [동영상] 등 태그
    )

    def __init__(self) -> None:
        if not _HAS_REQUESTS:
            raise ImportError(
                "TrendScraper에는 'requests'와 'beautifulsoup4' 패키지가 필요합니다. "
                "pip install requests beautifulsoup4 로 설치하세요."
            )
        self._session = _requests.Session()
        self._session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Referer":    "https://gall.dcinside.com/",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    # ──────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────

    def _clean(self, text: str) -> str:
        """HTML 태그·URL·앱 워터마크를 제거하고 공백을 정리한다."""
        return self._CLEAN_RE.sub(" ", text).strip()

    def _list_url(self, gallery_type: str, gallery_id: str, page: int) -> str:
        """갤러리 목록 URL 조립 (타입별 분기)."""
        from .config import GALLERY_PATTERNS
        base = GALLERY_PATTERNS.get(gallery_type, GALLERY_PATTERNS["mgallery"])
        return f"{base.format(gallery_id=gallery_id)}&page={page}"

    # ──────────────────────────────────────────
    # 공개 메서드
    # ──────────────────────────────────────────

    def fetch_post_list(
        self,
        gallery_id: str,
        gallery_type: str = "mgallery",
        page: int = 1,
    ) -> list[dict]:
        """갤러리 목록 페이지를 파싱하여 게시글 메타데이터 리스트를 반환한다.

        Returns:
            [{"post_no": str, "title": str, "views": int, "recommends": int,
              "author": str}, ...]
            에러 발생 시 빈 리스트 반환 (caller가 처리).
        """
        url = self._list_url(gallery_type, gallery_id, page)
        try:
            resp = self._session.get(url, timeout=12)
            resp.raise_for_status()
        except _requests.RequestException:
            return []

        soup = _BeautifulSoup(resp.text, "html.parser")
        posts: list[dict] = []

        for tr in soup.select("tr.ub-content"):
            try:
                post_no: str = tr.get("data-no", "").strip()
                if not post_no:
                    continue

                # ── 공지사항 스킵 ──────────────────────────────────────────────
                # 1) gall_num 텍스트가 숫자가 아닌 경우 ("공지", "설문" 등) 스킵
                num_el = tr.select_one("td.gall_num")
                if num_el:
                    num_text = num_el.get_text(strip=True)
                    if not num_text.isdigit():
                        continue
                # 2) 행 CSS class에 "notice" 포함 시 스킵 (DC Inside 추가 마커)
                row_class_list = tr.get("class") or []
                row_class_str = " ".join(row_class_list) if isinstance(row_class_list, list) else str(row_class_list)
                if "notice" in row_class_str.lower():
                    continue
                # ───────────────────────────────────────────────────────────────

                # 제목: gall_tit 셀 내부 첫 번째 일반 링크
                title_el = tr.select_one("td.gall_tit > a:not([class])")
                if title_el is None:
                    title_el = tr.select_one("td.gall_tit a")
                if title_el is None:
                    continue

                title = self._clean(title_el.get_text(strip=True))
                if not title:
                    continue

                # 조회수 / 추천수
                views_el = tr.select_one("td.gall_count")
                rec_el   = tr.select_one("td.gall_recommend")

                def _parse_int(el) -> int:
                    if el is None:
                        return 0
                    raw = el.get_text(strip=True).replace(",", "")
                    try:
                        return int(raw)
                    except ValueError:
                        return 0

                # 작성자 추출 (고정닉 nickname 또는 유동닉 IP)
                author = ""
                writer_el = tr.select_one("td.gall_writer")
                if writer_el:
                    nick_el = writer_el.select_one(".nickname")
                    if nick_el:
                        author = nick_el.get_text(strip=True)
                    else:
                        ip_el = writer_el.select_one(".ip")
                        if ip_el:
                            author = ip_el.get_text(strip=True)

                posts.append({
                    "post_no":    post_no,
                    "title":      title,
                    "views":      _parse_int(views_el),
                    "recommends": _parse_int(rec_el),
                    "author":     author,
                })
            except Exception:  # noqa: BLE001 — 개별 행 파싱 실패는 무시
                continue

        return posts

    def fetch_comments_ajax(
        self,
        gallery_id: str,
        post_no: str,
        gallery_type: str = "mgallery",
    ) -> list[str]:
        """DC Inside 내부 AJAX API로 댓글 텍스트 리스트를 반환한다.

        Returns:
            댓글 순수 텍스트 리스트.  실패 시 빈 리스트.
        """
        api_url = self._COMMENT_APIS.get(gallery_type, self._COMMENT_APIS["mgallery"])

        from .config import POST_URL_PATTERNS
        view_pattern = POST_URL_PATTERNS.get(gallery_type, POST_URL_PATTERNS["mgallery"])
        referer = view_pattern.format(gallery_id=gallery_id, post_id=post_no)

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type":     "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer":          referer,
        }
        payload = {
            "id":      gallery_id,
            "no":      post_no,
            "re_page": "1",
        }

        try:
            resp = self._session.post(
                api_url, data=payload, headers=headers, timeout=8
            )
            resp.raise_for_status()
            data = resp.json()
        except (_requests.RequestException, ValueError):
            return []

        comment_list = []
        if isinstance(data, dict):
            comment_list = data.get("comment_list", [])
        elif isinstance(data, list):
            comment_list = data

        texts: list[str] = []
        for c in comment_list:
            if not isinstance(c, dict):
                continue
            raw = c.get("memo") or c.get("comment") or c.get("content") or ""
            cleaned = self._clean(str(raw))
            if cleaned and len(cleaned) > 1:
                texts.append(cleaned)

        return texts

    def collect_trending(
        self,
        gallery_id: str,
        gallery_type: str = "mgallery",
        pages: int = 3,
        max_comments_per_post: int = 5,
        top_posts_per_page: int = 5,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """트렌드 수집 오케스트레이터.

        1. pages 개 목록 페이지에서 게시글 제목·메타 수집
        2. 추천수 상위 top_posts_per_page 개 글마다 AJAX로 댓글 수집
        3. 제목 최대 100개, 댓글 최대 100개 상한선 (메모리 보호)

        Returns:
            {
              "titles": list[str],
              "comments": list[str],
              "authors": list[str],    # 게시글 작성자 (닉네임/IP) — author dominance 분석용
              "gallery_id": str,
              "gallery_type": str,
              "collected_at": str  # ISO 8601
            }
        """
        def _log(msg: str) -> None:
            if progress_callback:
                progress_callback(msg)

        all_titles:   list[str] = []
        all_comments: list[str] = []
        all_authors:  list[str] = []   # 작성자 누적 리스트

        TITLE_CAP   = 100
        COMMENT_CAP = 100
        AUTHOR_CAP  = 200              # 상위 200개면 dominance 계산에 충분

        for page_no in range(1, pages + 1):
            _log(f"📄 목록 수집 중... ({page_no}/{pages} 페이지)")

            posts = self.fetch_post_list(gallery_id, gallery_type, page_no)
            if not posts:
                _log(f"⚠️ {page_no} 페이지 수집 실패 — 건너뜀")
                continue

            # 제목 + 작성자 누적 (상한 적용)
            for p in posts:
                if len(all_titles) >= TITLE_CAP:
                    break
                all_titles.append(p["title"])
                # 작성자 누적 (빈 문자열 제외, 상한 적용)
                if len(all_authors) < AUTHOR_CAP and p.get("author"):
                    all_authors.append(p["author"])

            # 추천수 Top N 글의 댓글 수집
            top = sorted(posts, key=lambda x: x.get("recommends", 0), reverse=True)
            top = top[:top_posts_per_page]

            for p in top:
                if len(all_comments) >= COMMENT_CAP:
                    break
                _log(f"💬 댓글 수집: [{p['post_no']}] {p['title'][:24]}...")
                cmts = self.fetch_comments_ajax(gallery_id, p["post_no"], gallery_type)
                # 개별 댓글 50자 trim — analyze_trend 토큰 절약
                trimmed = [c[:50] for c in cmts[:max_comments_per_post]]
                all_comments.extend(trimmed)
                _time.sleep(random.uniform(0.3, 0.7))  # 차단 회피 딜레이

            # 페이지 간 쿨다운
            if page_no < pages:
                _time.sleep(random.uniform(0.5, 1.0))

        _log(
            f"✅ 수집 완료 — 제목 {len(all_titles)}개 / "
            f"댓글 {len(all_comments)}개 / "
            f"작성자 {len(all_authors)}개"
        )
        return {
            "titles":       all_titles,
            "comments":     all_comments,
            "authors":      all_authors,
            "gallery_id":   gallery_id,
            "gallery_type": gallery_type,
            "collected_at": datetime.now().isoformat(),
        }
