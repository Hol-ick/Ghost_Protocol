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
import time
from typing import Callable, Optional

from playwright.async_api import async_playwright

from .config import USER_AGENTS, WRITE_URL_PATTERNS, get_write_url

# ══════════════════════════════════════════════
# 계정 관리
# ══════════════════════════════════════════════
ACCOUNTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "accounts.txt"
)

# 모든 계정에 공통으로 적용되는 비밀번호
_COMMON_PW = "q1w2e3r4%%"

LOGIN_URL = "https://sign.dcinside.com/login"


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

    async def start_browser(self, log: Optional[Callable] = None) -> None:
        """브라우저 시작 — 헤드리스 탐지 우회."""
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
            self._context = await self._browser.new_context(
                user_agent=ua,
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )
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
    ) -> bool:
        """DC Inside 갤러리에 글 작성.

        Args:
            gallery_id: 갤러리 ID
            title: 글 제목
            content: 글 본문
            log: 로그 콜백 함수

        Returns:
            True if post submitted successfully
        """
        page = self._page
        if not page:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        # ── ZWS 스텔스 워터마크 주입 ────────────────────────────────────────
        # ① 제목 끝에 Zero-Width Space 추가: 갤러리 목록 스크래핑 시 봇 게시글 식별 가능
        # ② 본문 끝에도 추가: 본문 수준 추적 및 Echo Chamber 효과 측정용
        # 두 문자 모두 인간의 눈에 보이지 않으며 DC Inside 렌더러가 그대로 보존함.
        _ZWS = "\u200b"
        title   = title   + _ZWS
        content = content + _ZWS
        # ─────────────────────────────────────────────────────────────────────

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
            return False

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

        # ── 제목 입력 ──
        if log:
            log(f"[POSTER] 📝 제목 입력 중: '{title[:30]}...'")

        # Jitter: #subject 클릭 전 짧은 마우스 이동 시뮬레이션
        await page.wait_for_timeout(int(random.uniform(500, 1200)))

        try:
            subject_input = page.locator("#subject")
            await subject_input.click()
            await subject_input.type(title, delay=int(random.uniform(70, 120)))
            await page.wait_for_timeout(int(random.uniform(400, 800)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] #subject 셀렉터 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

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
            return False

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

        # ── 본문 타이핑 ──
        if log:
            log("[POSTER] ⌨️ 본문 타이핑 시작...")

        # Jitter: 에디터 포커스 후 타이핑 시작 전 짧은 멈춤
        await page.wait_for_timeout(int(random.uniform(800, 1800)))

        try:
            await page.keyboard.type(content, delay=int(random.uniform(80, 130)))
            # Jitter: 타이핑 완료 후 검토하는 척 멈춤
            await page.wait_for_timeout(int(random.uniform(1000, 2500)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 본문 타이핑 중 에러: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

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
            # Jitter: 서버 처리 + 페이지 전환 대기
            await page.wait_for_timeout(int(random.uniform(3000, 5000)))
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] .btn_blue.btn_svc.write 클릭 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] 🚀 등록 버튼 클릭 완료 — 결과 확인 중...")

        # 글쓰기 성공 확인
        current_url = page.url
        is_posted = "write" not in current_url.lower()

        if log:
            if is_posted:
                log(f"[POSTER] 🎉 글 등록 성공! → {gallery_id}")
            else:
                log(f"[POSTER] [ERROR] 글 등록 실패 — 페이지가 이동하지 않음 (URL: {current_url[:60]})")
                await self._take_death_cam(log)

        return is_posted

    # ══════════════════════════════════════════════
    # 원스톱 실행
    # ══════════════════════════════════════════════

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
            {"success": bool, "account": str, "message": str}
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
            "message": "",
        }

        try:
            # 브라우저 시작
            await self.start_browser(log=log)

            # 로그인
            logged_in = await self.login(account["id"], account["pw"], log=log)
            if not logged_in:
                result["message"] = f"로그인 실패: {masked}"
                if log:
                    log(f"[POSTER] ❌ 작업 중단 — 로그인 실패 ({masked})")
                return result

            # 글쓰기
            posted = await self.write_post(gallery_id, title, content, log=log)
            if posted:
                result["success"] = True
                result["message"] = f"글 등록 성공! (계정: {masked})"
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
