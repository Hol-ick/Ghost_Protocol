"""Ghost Protocol v5.0 — Auto-poster module (Playwright).

Pipeline:
  accounts.txt → 아이디 목록 읽기 → 공통 비밀번호 매핑
  Playwright   → headless browser (anti-detection)
  DC Inside    → login → WAF delay → write post → done
  log_callback → real-time UI logging
"""

import asyncio
import os
import random
import re
import time
from pathlib import Path
from typing import Callable, Optional

from playwright.async_api import async_playwright

from .config import USER_AGENTS, WRITE_URL_PATTERNS, get_write_url, get_view_url
from .ledger import ledger_add

# ══════════════════════════════════════════════
# 계정 관리
# ══════════════════════════════════════════════
ACCOUNTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "accounts.txt"
)

# 모든 계정에 공통으로 적용되는 비밀번호
_COMMON_PW = "q1w2e3r4%%"

LOGIN_URL = "https://sign.dcinside.com/login"

# ══════════════════════════════════════════════
# 세션 캐시 (Playwright storage_state 기반)
# ══════════════════════════════════════════════
# 계정별 쿠키/로컬스토리지를 sessions/<account>.json 에 보관.
# 봇 실행 시 저장된 세션을 먼저 시도(Fast-path)하고,
# 세션 만료 시에만 타이핑 로그인(Slow-path) 후 세션을 갱신한다.
_SESSIONS_DIR = Path(__file__).parent.parent / "sessions"


def _session_path(account_id: str) -> Path:
    """계정 ID → sessions/session_<safe_id>.json 경로 반환.

    account_id의 영숫자/하이픈/밑줄 이외 문자는 '_' 로 치환하여
    파일명 안전성을 보장한다.
    """
    safe = re.sub(r"[^\w\-]", "_", account_id)
    return _SESSIONS_DIR / f"session_{safe}.json"


def _sessions_dir_init() -> None:
    """sessions/ 디렉토리 생성 + 소유자 전용 권한 설정.

    Unix: 0o700 (rwx------), Windows: mkdir만 실행 (chmod 무시).
    """
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_SESSIONS_DIR, 0o700)
    except OSError:
        pass  # Windows — no-op


def load_accounts() -> list[dict]:
    """accounts.txt에서 아이디 목록을 읽어 공통 비밀번호와 매핑하여 반환.

    accounts.txt 형식:
        한 줄에 아이디 하나 (공백 라인·앞뒤 공백 자동 무시)

    Returns:
        [{"id": "user1", "pw": "q1w2e3r4%%"}, ...]

    Raises:
        FileNotFoundError: accounts.txt가 없을 때
        ValueError: 파일이 비어있을 때
    """
    if not os.path.exists(ACCOUNTS_PATH):
        raise FileNotFoundError(
            f"[POSTER] ❌ accounts.txt가 없습니다: {ACCOUNTS_PATH}\n"
            "프로젝트 루트에 accounts.txt 파일을 만들고 아이디를 한 줄에 하나씩 입력하세요."
        )

    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    ids = [line.strip() for line in lines if line.strip()]

    if not ids:
        raise ValueError(
            f"[POSTER] ❌ accounts.txt가 비어있습니다: {ACCOUNTS_PATH}\n"
            "아이디를 한 줄에 하나씩 입력하세요."
        )

    accounts = [{"id": uid, "pw": _COMMON_PW} for uid in ids]
    random.shuffle(accounts)   # 로드 시점 1회 셔플 → 큐 방식의 라운드로빈 베이스
    return accounts


def pick_random_account() -> dict:
    """계정 목록에서 무작위로 하나 선택."""
    accounts = load_accounts()
    return random.choice(accounts)


def _mask_id(user_id: str) -> str:
    """보안상 ID 일부만 표시 (예: abcdef123 → ****ef123)."""
    if len(user_id) <= 4:
        return "****" + user_id[-1:]
    return "****" + user_id[-4:]


class GhostPoster:
    """DC Inside 자동 글쓰기 — Playwright 기반 + 실시간 로깅."""

    def __init__(self, headless: bool = False, gallery_type: str = "mgallery"):
        """
        Args:
            headless: 브라우저 숨김 모드 (디버깅용 기본값: False)
            gallery_type: 갤러리 타입 (board / mgallery / mini)
        """
        self._headless = headless
        self._gallery_type = gallery_type
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    async def _take_death_cam(self, log: Optional[Callable] = None) -> None:
        """에러 직전 스크린샷 캡처 (Death Cam) — logs/screenshots/ 저장."""
        if not self._page:
            return
        try:
            # logs/screenshots/ 폴더 자동 생성
            screenshots_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "logs", "screenshots"
            )
            os.makedirs(screenshots_dir, exist_ok=True)
            fname = os.path.join(screenshots_dir, f"error_screenshot_{int(time.time())}.png")
            await self._page.screenshot(path=fname)
            if log:
                log(f"[POSTER] 📸 에러 화면 스크린샷 저장 완료: {fname}")
        except Exception:
            if log:
                log("[POSTER] 📸 스크린샷 저장 실패 (브라우저 이미 닫힘?)")

    # ══════════════════════════════════════════════
    # 브라우저 관리 (scraper.py와 동일한 스텔스 설정)
    # ══════════════════════════════════════════════

    async def start_browser(
        self,
        log: Optional[Callable] = None,
        storage_state: Optional[str] = None,
    ) -> None:
        """브라우저 시작 — 헤드리스 탐지 우회.

        Args:
            storage_state: sessions/*.json 경로 문자열.
                           지정 시 해당 파일에서 쿠키/로컬스토리지를 복원.
                           None이면 새 빈 컨텍스트로 시작.
        """
        if log:
            log("[POSTER] 🌐 브라우저 스텔스 모드 시작...")

        try:
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
            _ctx_kwargs: dict = {
                "user_agent": ua,
                "locale": "ko-KR",
                "timezone_id": "Asia/Seoul",
            }
            if storage_state:
                _ctx_kwargs["storage_state"] = storage_state
                if log:
                    log("[POSTER] 🍪 저장된 세션 파일 로드 중...")
            self._context = await self._browser.new_context(**_ctx_kwargs)
            # navigator.webdriver 속성 숨기기
            await self._context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            self._page = await self._context.new_page()

            # ── JS 팝업 자동 감지 & 닫기 리스너 ──
            # IP 차단, 비밀번호 오류, CAPTCHA 등 alert/confirm 팝업 방어
            async def _handle_dialog(dialog):
                try:
                    msg = dialog.message
                    if log:
                        log(f"[POSTER] ⚠️ 팝업 감지 (자동 닫기): {msg[:100]}")
                    await dialog.dismiss()
                except Exception:
                    pass

            self._page.on("dialog", lambda d: asyncio.get_event_loop().create_task(_handle_dialog(d)))

            if log:
                mode = "Headless" if self._headless else "Visible"
                log(f"[POSTER] ✅ 브라우저 시작 완료 ({mode} Mode, UA: {ua[:40]}...)")
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 브라우저 시작 실패: {str(e)[:100]}")
            raise

    async def close_browser(self, log: Optional[Callable] = None) -> None:
        """브라우저 종료.

        중첩 try-finally 구조로 browser.close()가 예외를 던져도
        playwright.stop()이 반드시 실행되도록 보장 (Flaw #3 수정).
        """
        if log:
            log("[POSTER] 🔒 브라우저 종료 중...")

        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            if log:
                log(f"[POSTER] ⚠️ 브라우저 종료 예외 (무시하고 계속): {str(e)[:80]}")
        finally:
            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception as e:
                if log:
                    log(f"[POSTER] ⚠️ Playwright 종료 예외 (무시): {str(e)[:80]}")
            self._browser = None
            self._playwright = None
            self._context = None
            self._page = None

        if log:
            log("[POSTER] ✅ 브라우저 종료 완료")

    # ══════════════════════════════════════════════
    # 세션 캐시 헬퍼
    # ══════════════════════════════════════════════

    async def _is_logged_in_fast(
        self, gallery_id: str, log: Optional[Callable] = None
    ) -> bool:
        """저장된 세션으로 글쓰기 페이지 직접 진입 가능 여부 확인 (Fast-path).

        글쓰기 URL에 이동 후:
          - 로그인 페이지로 리디렉트  →  세션 만료  →  False 반환
          - #subject 입력창 발견      →  세션 유효  →  True 반환
          - 그 외 (WAF / 예외)       →  False 반환 (Slow-path 위임)

        True 반환 시 현재 페이지는 이미 글쓰기 URL이므로
        write_post() 내부 goto()가 동일 URL을 재로드하게 됨.
        """
        page = self._page
        if not page:
            return False

        write_url = get_write_url(self._gallery_type, gallery_id)
        if log:
            log("[POSTER] ⚡ Fast-path: 저장된 세션으로 글쓰기 페이지 직접 진입 시도...")

        try:
            await page.goto(write_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(int(random.uniform(1500, 2500)))
        except Exception as e:
            if log:
                log(f"[POSTER] ⚡ Fast-path 탐색 실패: {str(e)[:80]}")
            return False

        # 로그인 페이지로 리디렉트됐으면 세션 만료
        if "login" in page.url.lower():
            if log:
                log("[POSTER] ⚡ Fast-path: 세션 만료 (로그인 페이지 리디렉트) → Slow-path 전환")
            return False

        # #subject 입력창으로 글쓰기 에디터 진입 확인
        try:
            await page.locator("#subject").wait_for(state="attached", timeout=5000)
            if log:
                log("[POSTER] ⚡ Fast-path: 세션 유효 — 로그인 건너뜀 ✅")
            return True
        except Exception:
            if log:
                log("[POSTER] ⚡ Fast-path: #subject 미발견 — 세션 불확실 → Slow-path 전환")
            return False

    async def _save_session_atomic(
        self, sess_path: Path, log: Optional[Callable] = None
    ) -> None:
        """브라우저 컨텍스트의 세션(쿠키+로컬스토리지)을 원자적으로 저장.

        temp 파일에 먼저 쓴 뒤 os.replace()로 교체 → 부분 쓰기 방지.
        Unix에서는 0o600 권한으로 다른 사용자 접근 차단.
        예외 발생 시 조용히 무시하고 임시 파일을 정리한다.
        """
        if not self._context:
            return
        tmp = sess_path.with_suffix(".tmp")
        try:
            _sessions_dir_init()
            await self._context.storage_state(path=str(tmp))
            os.replace(tmp, sess_path)
            try:
                os.chmod(sess_path, 0o600)  # Unix: rw-------
            except OSError:
                pass  # Windows — no-op
            if log:
                log(f"[SESSION] 💾 세션 저장 완료: {sess_path.name}")
        except Exception as e:
            if log:
                log(f"[SESSION] ⚠️ 세션 저장 실패 (무시하고 계속): {str(e)[:80]}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # ══════════════════════════════════════════════
    # 로그인
    # ══════════════════════════════════════════════

    async def login(
        self, user_id: str, password: str, log: Optional[Callable] = None
    ) -> bool:
        """DC Inside 로그인.

        Args:
            user_id: 디시인사이드 아이디
            password: 비밀번호
            log: 로그 콜백 함수

        Returns:
            True if login successful
        """
        page = self._page
        if not page:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        masked = _mask_id(user_id)

        if log:
            log(f"[POSTER] 🔑 로그인 페이지 진입 중... (계정: {masked})")

        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
            # Jitter: 페이지 로드 후 인간적인 정착 딜레이
            _jitter = int(random.uniform(2000, 4500))
            if log:
                log(f"[POSTER] ⏳ 페이지 안정화 대기... ({_jitter}ms)")
            await page.wait_for_timeout(_jitter)
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 로그인 페이지 로드 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] ⌨️ 아이디 입력 중 (human typing, delay=100ms)...")

        try:
            id_input = page.locator(
                "input[placeholder='식별 코드'], #user_id"
            ).locator("visible=true").first
            await id_input.click()
            # fill() → type(): 인간의 타이핑 속도 모방 (100ms/char)
            await id_input.type(user_id, delay=100)
            # Jitter: 필드 간 이동 전 짧은 휴식
            await page.wait_for_timeout(int(random.uniform(400, 900)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 아이디 셀렉터 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] ⌨️ 비밀번호 입력 중 (human typing, delay=100ms)...")

        try:
            pw_input = page.locator(
                "input[placeholder='비밀번호'], input[type='password']"
            ).locator("visible=true").first
            await pw_input.click()
            # fill() → type(): 인간의 타이핑 속도 모방 (100ms/char)
            await pw_input.type(password, delay=100)
            # Jitter: 로그인 버튼 클릭 전 짧은 생각하는 시간
            await page.wait_for_timeout(int(random.uniform(600, 1500)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 비밀번호 셀렉터 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] 🖱️ 로그인 버튼 클릭...")

        try:
            login_btn = page.locator(
                "button, input[type='submit'], .btn_login"
            ).filter(has_text="로그인")
            await login_btn.first.click()
            # Jitter: 로그인 후 서버 응답 대기 (인간적인 속도)
            await page.wait_for_timeout(int(random.uniform(3000, 5000)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 로그인 버튼(텍스트: '로그인') 클릭 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        # 로그인 성공 확인
        current_url = page.url
        is_logged_in = "login" not in current_url.lower()

        if log:
            if is_logged_in:
                log(f"[POSTER] ✅ 로그인 성공! (계정: {masked})")
            else:
                log(f"[POSTER] [ERROR] 로그인 실패 — 페이지가 이동하지 않음 (URL: {current_url[:60]})")
                await self._take_death_cam(log)

        return is_logged_in

    # ══════════════════════════════════════════════
    # 글쓰기
    # ══════════════════════════════════════════════

    async def write_post(
        self,
        gallery_id: str,
        title: str,
        content: str,
        log: Optional[Callable] = None,
    ) -> Optional[str]:
        """DC Inside 갤러리에 글 작성.

        Args:
            gallery_id: 갤러리 ID
            title: 글 제목
            content: 글 본문
            log: 로그 콜백 함수

        Returns:
            post_no (str) if posting succeeded, None if failed.
            post_no may be "" if DC Inside redirect URL lacked the no= param.
        """
        page = self._page
        if not page:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        # ── Jitter: 로그인 후 세션 안정화 (가변 딜레이) ──
        _session_jitter = int(random.uniform(2000, 4500))
        if log:
            log(f"[POSTER] ☕ 로그인 후 세션 안정화 대기 중... ({_session_jitter}ms)")
        await page.wait_for_timeout(_session_jitter)

        # 글쓰기 페이지 이동 — 타입별 URL 동적 생성
        write_url = get_write_url(self._gallery_type, gallery_id)

        if log:
            log(f"[POSTER] 📄 글쓰기 페이지 이동 중... ({self._gallery_type}/{gallery_id})")

        try:
            await page.goto(write_url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 글쓰기 페이지 로드 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return None

        # ── WAF/Cloudflare 빈 화면 방어 ──
        # "Just a moment..." 페이지가 뜨면 최대 15초 대기하며 우회 완료 대기
        _waf_start = time.time()
        _waf_passed = False
        while time.time() - _waf_start < 15:
            try:
                _page_content = await page.content()
                _is_waf = (
                    "just a moment" in _page_content.lower()
                    or len(_page_content) < 1500
                )
                if not _is_waf:
                    _waf_passed = True
                    break
                if log:
                    log("[POSTER] 🛡️ WAF/Cloudflare 감지 — 우회 대기 중...")
            except Exception:
                break
            await page.wait_for_timeout(2000)

        if not _waf_passed:
            if log:
                log("[POSTER] ⚠️ WAF 우회 타임아웃 (15초) — 계속 진행 시도...")

        # Jitter: 페이지 렌더링 완료 후 인간적인 정착 딜레이
        _render_jitter = int(random.uniform(1500, 3000))
        await page.wait_for_timeout(_render_jitter)

        if log:
            log("[POSTER] ✍️ 갤러리 글쓰기 페이지 로드 완료")

        # ── 제목 입력 (마커 없음 — 마커는 본문으로 이동) ──
        if log:
            log(f"[POSTER] 📝 제목 입력 중: '{title[:30]}...'")

        # Jitter: #subject 클릭 전 짧은 마우스 이동 시뮬레이션
        await page.wait_for_timeout(int(random.uniform(500, 1200)))

        try:
            subject_input = page.locator("#subject")
            await subject_input.click()
            await subject_input.type(title.strip(), delay=int(random.uniform(70, 120)))
            await page.wait_for_timeout(int(random.uniform(400, 800)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] #subject 셀렉터 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return None

        if log:
            log("[POSTER] ✅ 제목 입력 완료")

        # 본문 입력 (유니버설 에디터 셀렉터)
        if log:
            log("[POSTER] 🕵️‍♂️ 에디터 영역 탐색 중...")

        editor_found = False
        try:
            # 시도 1: 일반적인 웹에디터의 iframe 내부 body
            editor = page.frame_locator("iframe").last.locator("body")
            await editor.click(timeout=3000)
            editor_found = True
            if log:
                log("[POSTER] ✅ 에디터 발견 (iframe 내부 body)")
        except Exception:
            pass

        if not editor_found:
            try:
                # 시도 2: 최신형 에디터 (contenteditable 속성을 가진 div)
                editor = page.locator("[contenteditable='true']").first
                await editor.click(timeout=3000)
                editor_found = True
                if log:
                    log("[POSTER] ✅ 에디터 발견 (contenteditable div)")
            except Exception:
                pass

        if not editor_found:
            if log:
                log("[POSTER] [ERROR] 에디터 영역을 찾을 수 없습니다 (iframe/contenteditable 모두 실패)")
            await self._take_death_cam(log)
            return None

        if log:
            log("[POSTER] ✅ 에디터 포커스 완료.")

        # ── 🖼️ 미끼 짤방: paste 이벤트 시뮬레이션 ──────────────────────────
        # 수정 이력:
        #   구버전: ClipboardEvent('paste', { clipboardData: dt }) + page.evaluate(fn, editor)
        #   문제 1: Chromium은 ClipboardEvent 생성자의 clipboardData 옵션을 무시 →
        #           event.clipboardData가 빈 DataTransfer로 남아 에디터가 이미지를 읽지 못함.
        #           ("Cannot read properties of undefined (reading 'dispatch')" 에러 발생)
        #   문제 2: editor가 iframe 내부 요소일 때 page.evaluate(fn, elementHandle)는
        #           cross-frame 참조 오류를 유발할 수 있음.
        #   해결책:
        #   (A) editor.evaluate(fn) 사용 → 올바른 프레임 컨텍스트에서 실행
        #   (B) ClipboardEvent 대신 기본 Event + Object.defineProperty로 clipboardData 강제 주입
        try:
            if log:
                log("[POSTER] 🖼️ 1x1 미끼 짤방 붙여넣기 시뮬레이션 중...")

            paste_js = """(el) => {
                // 1×1 투명 PNG (Base64 인코딩)
                const b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
                const bin = atob(b64);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                const blob = new Blob([arr], {type: 'image/png'});
                const file = new File([blob], 'bait.png', {type: 'image/png'});

                const dt = new DataTransfer();
                dt.items.add(file);

                // Chromium: ClipboardEvent 생성자에서 clipboardData를 설정해도
                // 실제 event.clipboardData는 read-only라 반영되지 않음.
                // → 표준 Event + Object.defineProperty로 clipboardData를 강제 주입.
                const evt = new Event('paste', { bubbles: true, cancelable: true });
                Object.defineProperty(evt, 'clipboardData', {
                    value: dt,
                    configurable: true,
                });
                el.dispatchEvent(evt);
            }"""

            # editor.evaluate(fn) — iframe 내부 에디터도 올바른 프레임 컨텍스트에서 실행
            await editor.evaluate(paste_js)
            # 디시 서버 이미지 업로드 대기
            await page.wait_for_timeout(2000)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(300)
        except Exception as e:
            if log:
                log(f"[POSTER] ⚠️ 짤방 삽입 실패 (무시하고 계속): {str(e)[:80]}")

        # ── 본문 타이핑 (전각 마침표 스텔스 마커 본문 끝에 삽입) ──
        # 제목 끝 마커는 HTML 목록 페이지에서 보여 식별 위험 존재.
        # 본문 끝은 목록에 노출되지 않아 스텔스성이 훨씬 높음.
        # 이중 삽입 방지: LLM이 이미 ．로 끝나는 본문을 드물게 생성하는 엣지케이스 처리.
        _c_stripped  = content.rstrip()
        marked_content = _c_stripped if _c_stripped.endswith("\uff0e") else _c_stripped + "\uff0e"

        if log:
            log("[POSTER] ⌨️ 본문 타이핑 시작... [전각 마침표 마커 본문 말미 삽입]")

        # Jitter: 에디터 포커스 후 타이핑 시작 전 짧은 멈춤
        await page.wait_for_timeout(int(random.uniform(800, 1800)))

        try:
            await page.keyboard.type(marked_content, delay=int(random.uniform(80, 130)))
            # Jitter: 타이핑 완료 후 검토하는 척 멈춤
            await page.wait_for_timeout(int(random.uniform(1000, 2500)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 본문 타이핑 중 에러: {str(e)[:100]}")
            await self._take_death_cam(log)
            return None

        if log:
            line_count = len(content.split("\n"))
            log(f"[POSTER] ✅ 본문 입력 완료 ({line_count}줄, {len(content)}자)")

        # 등록 버튼 클릭
        if log:
            log("[POSTER] 🚀 등록 버튼 클릭 중...")

        # Jitter: 제출 버튼 클릭 전 마지막 망설임 딜레이
        await page.wait_for_timeout(int(random.uniform(1200, 2800)))

        try:
            submit_btn = page.locator(".btn_blue.btn_svc.write")
            await submit_btn.click()
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] .btn_blue.btn_svc.write 클릭 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return None

        if log:
            log("[POSTER] 🚀 등록 버튼 클릭 완료 — board/view 리디렉트 대기 중...")

        # ── 리디렉트 대기: board/view URL로 전환될 때까지 최대 12초 ───────────
        # wait_for_timeout 고정 대기 방식은 서버 응답 지연 시 race condition 발생.
        # wait_for_url로 실제 URL 변경을 감지해야 post_no 추출 신뢰성 보장.
        try:
            await page.wait_for_url("**/board/view/**", timeout=12000)
        except Exception:
            # 타임아웃 또는 DC Inside가 다른 URL 패턴으로 리디렉트한 경우
            # 추가 2초 대기 후 현재 URL로 판단
            if log:
                log("[POSTER] ⚠️ board/view 리디렉트 감지 실패 — 2초 추가 대기 후 URL 확인")
            await page.wait_for_timeout(2000)

        # 글쓰기 성공 확인: write 페이지를 벗어났으면 성공
        current_url = page.url
        is_posted = "write" not in current_url.lower()

        if not is_posted:
            if log:
                log(f"[POSTER] [ERROR] 글 등록 실패 — 페이지가 이동하지 않음 (URL: {current_url[:70]})")
            await self._take_death_cam(log)
            return None

        # ── post_no 추출 (1차: URL 파싱) ────────────────────────────────────
        # 예: .../board/view/?id=hwhy&no=5840 → "5840"
        _m = re.search(r"[?&]no=(\d+)", current_url)
        post_no = _m.group(1) if _m else ""

        # ── post_no 추출 (2차 Fallback: DOM input[name='no']) ────────────────
        # DC Inside 글 보기 페이지의 댓글 form에 숨김 input으로 포함되어 있음.
        if not post_no:
            try:
                _no_el = page.locator("input[name='no']").first
                _val = await _no_el.get_attribute("value", timeout=3000)
                post_no = (_val or "").strip()
            except Exception:
                pass

        if log:
            _no_label = f" (no={post_no})" if post_no else " (no 파라미터 추출 불가)"
            log(f"[POSTER] 🎉 글 등록 성공! → {gallery_id}{_no_label}")

        return post_no

    # ══════════════════════════════════════════════
    # 댓글 작성
    # ══════════════════════════════════════════════

    async def write_comment(
        self,
        gallery_id: str,
        post_no: str,
        comment: str,
        log: Optional[Callable] = None,
    ) -> bool:
        """DC Inside 게시글에 댓글 작성.

        Args:
            gallery_id: 갤러리 ID
            post_no: 댓글 달 게시글 번호 (숫자 문자열)
            comment: 댓글 내용 (1줄 권장)
            log: 로그 콜백 함수

        Returns:
            True if comment submitted successfully
        """
        page = self._page
        if not page:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        view_url = get_view_url(self._gallery_type, gallery_id, post_no)

        if log:
            log(f"[POSTER] 💬 글보기 이동 중... (#{post_no})")

        try:
            await page.goto(view_url, wait_until="domcontentloaded", timeout=20000)
            # 페이지 안정화 딜레이
            await page.wait_for_timeout(int(random.uniform(2000, 4000)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 글보기 페이지 로드 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log(f"[POSTER] 🕵️ 댓글 입력창 탐색 중...")

        # ── 댓글 textarea 탐색 (DC Inside 멀티 셀렉터) ──
        # DC Inside는 갤러리 타입·테마에 따라 셀렉터가 다를 수 있어 순서대로 시도.
        comment_input = None
        for _sel in [
            "#re_txt",
            ".cmt_write_box textarea",
            "textarea[name='memo']",
            ".reply_write textarea",
            "textarea",
        ]:
            try:
                el = page.locator(_sel).first
                await el.wait_for(state="attached", timeout=3000)
                comment_input = el
                if log:
                    log(f"[POSTER] ✅ 댓글 입력창 발견 ({_sel})")
                break
            except Exception:
                continue

        if comment_input is None:
            if log:
                log("[POSTER] [ERROR] 댓글 입력창을 찾을 수 없습니다 (모든 셀렉터 실패)")
            await self._take_death_cam(log)
            return False

        # ── 댓글 타이핑 ──
        try:
            await comment_input.scroll_into_view_if_needed()
            await page.wait_for_timeout(int(random.uniform(200, 400)))
            await comment_input.click(force=True)
            await page.wait_for_timeout(int(random.uniform(400, 900)))
            await comment_input.type(comment, delay=int(random.uniform(60, 110)))
            await page.wait_for_timeout(int(random.uniform(500, 1200)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 댓글 타이핑 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log(f"[POSTER] ✅ 댓글 입력 완료 ({len(comment)}자). 등록 버튼 클릭 중...")

        # ── 등록 버튼 탐색 (멀티 셀렉터 + 텍스트 fallback) ──
        submitted = False
        for _sel in [
            ".btn_comment_ok",
            ".btn_write.comment",
            ".write_btn",
            ".btn_submit",
        ]:
            try:
                btn = page.locator(_sel).first
                await btn.wait_for(state="attached", timeout=2000)
                await btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(int(random.uniform(600, 1200)))
                await btn.click(force=True)
                submitted = True
                if log:
                    log(f"[POSTER] 🖱️ 등록 버튼 클릭 ({_sel})")
                break
            except Exception:
                continue

        if not submitted:
            # 텍스트 "등록" 버튼 fallback
            try:
                btn = page.locator("button").filter(has_text="등록").last
                await btn.wait_for(state="attached", timeout=2000)
                await btn.scroll_into_view_if_needed()
                await page.wait_for_timeout(int(random.uniform(600, 1200)))
                await btn.click(force=True)
                submitted = True
                if log:
                    log("[POSTER] 🖱️ 등록 버튼 클릭 (텍스트 fallback)")
            except Exception:
                pass

        if not submitted:
            if log:
                log("[POSTER] [ERROR] 댓글 등록 버튼을 찾을 수 없습니다")
            await self._take_death_cam(log)
            return False

        # 서버 처리 대기
        await page.wait_for_timeout(int(random.uniform(2500, 4500)))

        # 댓글 등록 성공 확인: URL이 write 페이지가 아니면 OK
        # DC Inside는 댓글 등록 후 동일 페이지에 머무름 → 예외 URL 체크 불필요
        # 에러 팝업(alert) 발생 시 _handle_dialog 리스너가 자동 dismiss 처리됨
        is_commented = True  # 버튼 클릭까지 성공하면 성공으로 간주

        if log:
            if is_commented:
                log(f"[POSTER] ✅ 댓글 등록 완료! (#{post_no})")

        return is_commented

    # ══════════════════════════════════════════════
    # 원스톱 실행
    # ══════════════════════════════════════════════

    async def auto_comment(
        self,
        gallery_id: str,
        post_no: str,
        comment: str,
        account: Optional[dict] = None,
        log_callback: Optional[Callable] = None,
    ) -> dict:
        """로그인 → 댓글 작성 → 브라우저 종료 원스톱 실행.

        Args:
            gallery_id: 갤러리 ID
            post_no: 댓글 달 게시글 번호
            comment: 댓글 내용
            account: {"id": ..., "pw": ...} (None이면 랜덤 선택)
            log_callback: 실시간 로그 콜백

        Returns:
            {"success": bool, "account": str, "message": str}
        """
        log = log_callback

        if account is None:
            account = pick_random_account()

        masked = _mask_id(account["id"])
        if log:
            log(f"[POSTER] 🎭 댓글 계정 선택: ID={masked}")

        result = {
            "success": False,
            "account": account["id"],
            "message": "",
        }

        try:
            # ── 세션 캐시 준비 ──────────────────────────────────────────────
            _sessions_dir_init()
            sess_path    = _session_path(account["id"])
            _has_session = sess_path.exists()

            # 브라우저 시작 (저장된 세션이 있으면 쿠키/로컬스토리지 복원)
            await self.start_browser(
                log=log,
                storage_state=str(sess_path) if _has_session else None,
            )

            # ── Fast-path: 저장된 세션으로 글쓰기 페이지 직접 진입 시도 ──
            # 댓글은 글보기 페이지에서 작성하지만, 글쓰기 페이지 진입 가능 여부로
            # 로그인 상태를 판별 (댓글 전용 URL에는 세션 검증 UI 요소가 없어 판단 불가).
            _session_valid = False
            if _has_session:
                _session_valid = await self._is_logged_in_fast(gallery_id, log=log)

            # ── Slow-path: 세션 없거나 만료 → ID/PW 타이핑 로그인 ──────────
            if not _session_valid:
                logged_in = await self.login(account["id"], account["pw"], log=log)
                if not logged_in:
                    result["message"] = f"로그인 실패: {masked}"
                    if log:
                        log(f"[POSTER] ❌ 댓글 중단 — 로그인 실패 ({masked})")
                    return result
                # 로그인 성공 직후 세션 저장 (다음 실행 Fast-path 대비)
                await self._save_session_atomic(sess_path, log=log)

            commented = await self.write_comment(gallery_id, post_no, comment, log=log)
            if commented:
                result["success"] = True
                result["message"] = f"댓글 등록 성공! (계정: {masked}, 글: #{post_no})"
                # 댓글 성공 후 세션 갱신 (쿠키 TTL 연장)
                await self._save_session_atomic(sess_path, log=log)
                if log:
                    log(f"[POSTER] ✅ 댓글 완료 (계정: {masked}, 글: #{post_no})")
            else:
                result["message"] = "댓글 등록 실패"
                if log:
                    log("[POSTER] ❌ 댓글 작업 실패")

        except Exception as e:
            err_msg = str(e)[:150]
            result["message"] = f"오류 발생: {err_msg}"
            if log:
                log(f"[POSTER] [ERROR] 댓글 예외: {err_msg}")
            await self._take_death_cam(log)

        finally:
            await self.close_browser(log=log)

        return result

    async def auto_post(
        self,
        gallery_id: str,
        title: str,
        content: str,
        account: Optional[dict] = None,
        log_callback: Optional[Callable] = None,
    ) -> dict:
        """로그인 → 글쓰기 → 브라우저 종료 원스톱 실행.

        Args:
            gallery_id: 갤러리 ID
            title: 글 제목
            content: 글 본문
            account: {"id": ..., "pw": ...} (None이면 랜덤 선택)
            log_callback: 실시간 로그 콜백 (msg: str) -> None

        Returns:
            {"success": bool, "account": str, "post_no": str, "message": str}
        """
        log = log_callback

        # 계정 선택
        if account is None:
            account = pick_random_account()

        masked = _mask_id(account["id"])
        if log:
            log(f"[POSTER] 🎭 랜덤 계정 선택 완료: ID={masked}")

        result = {
            "success": False,
            "account": account["id"],
            "post_no": "",
            "message": "",
        }

        try:
            # ── 세션 캐시 준비 ──────────────────────────────────────────────
            _sessions_dir_init()
            sess_path   = _session_path(account["id"])
            _has_session = sess_path.exists()

            # 브라우저 시작 (저장된 세션이 있으면 쿠키/로컬스토리지 복원)
            await self.start_browser(
                log=log,
                storage_state=str(sess_path) if _has_session else None,
            )

            # ── Fast-path: 저장된 세션으로 글쓰기 페이지 직접 진입 시도 ──
            _session_valid = False
            if _has_session:
                _session_valid = await self._is_logged_in_fast(gallery_id, log=log)

            # ── Slow-path: 세션 없거나 만료 → ID/PW 타이핑 로그인 ──────────
            if not _session_valid:
                logged_in = await self.login(account["id"], account["pw"], log=log)
                if not logged_in:
                    result["message"] = f"로그인 실패: {masked}"
                    if log:
                        log(f"[POSTER] ❌ 작업 중단 — 로그인 실패 ({masked})")
                    return result
                # 로그인 성공 직후 세션 저장 (다음 실행 Fast-path 대비)
                await self._save_session_atomic(sess_path, log=log)

            # ── 글쓰기 — write_post()는 post_no(str) 반환, 실패 시 None ──
            post_no = await self.write_post(gallery_id, title, content, log=log)
            if post_no is not None:
                result["success"] = True
                result["post_no"] = post_no
                result["message"] = (
                    f"글 등록 성공! (계정: {masked}"
                    + (f", no={post_no}" if post_no else "")
                    + ")"
                )
                # 글 등록 성공 후 세션 갱신 (쿠키 TTL 연장)
                await self._save_session_atomic(sess_path, log=log)
                # ── 로컬 원장 기록: ledger에 post_no 추가 ────────────────────
                # gallery_id 정규화: ledger.py가 정규화를 이중으로 수행하지만 방어적으로 적용
                if post_no:
                    ledger_add(gallery_id, post_no)
                    if log:
                        log(f"[LEDGER] ✅ 글 번호 {post_no} 장부 기록 완료 ({gallery_id})")
                else:
                    if log:
                        log("[LEDGER] ⚠️ post_no 없음 — 장부 기록 생략 (점유율 집계 제외)")
                if log:
                    log(f"[POSTER] ✅ 전체 작업 완료! (계정: {masked}, 갤러리: {gallery_id})")
            else:
                result["message"] = "글 등록 실패 (버튼 클릭 후 페이지 이동 안 됨)"
                if log:
                    log("[POSTER] ❌ 전체 작업 실패 — 글 등록 단계에서 중단")

        except Exception as e:
            err_msg = str(e)[:150]
            result["message"] = f"오류 발생: {err_msg}"
            if log:
                log(f"[POSTER] [ERROR] 예외 발생: {err_msg}")
            await self._take_death_cam(log)

        finally:
            await self.close_browser(log=log)

        return result
