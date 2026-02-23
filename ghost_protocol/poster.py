"""Ghost Protocol v5.0 — Auto-poster module (Playwright).

Pipeline:
  accounts.json → random account select
  Playwright    → headless browser (anti-detection)
  DC Inside     → login → WAF delay → write post → done
  log_callback  → real-time UI logging
"""

import json
import os
import random
import time
from typing import Callable, Optional

from playwright.async_api import async_playwright

from .config import USER_AGENTS

# ══════════════════════════════════════════════
# 계정 관리
# ══════════════════════════════════════════════
ACCOUNTS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "accounts.json"
)

# 글쓰기 URL 패턴 (갤러리 타입별)
WRITE_URL_PATTERNS = {
    "board": "https://gall.dcinside.com/board/write/?id={gallery_id}",
    "mgallery": "https://gall.dcinside.com/mgallery/board/write/?id={gallery_id}",
    "mini": "https://gall.dcinside.com/mini/board/write/?id={gallery_id}",
}

LOGIN_URL = "https://sign.dcinside.com/login"


def load_accounts() -> list[dict]:
    """accounts.json에서 계정 목록을 로드.

    Returns:
        [{"id": "user1", "pw": "pass1"}, ...]

    Raises:
        FileNotFoundError: accounts.json이 없을 때
        ValueError: 파일 형식이 잘못되었을 때
    """
    if not os.path.exists(ACCOUNTS_PATH):
        raise FileNotFoundError(
            f"accounts.json이 없습니다: {ACCOUNTS_PATH}\n"
            '[{"id": "아이디", "pw": "비밀번호"}] 형식으로 생성하세요.'
        )

    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    if not isinstance(accounts, list) or not accounts:
        raise ValueError("accounts.json이 비어있거나 형식이 잘못되었습니다.")

    for acc in accounts:
        if "id" not in acc or "pw" not in acc:
            raise ValueError('accounts.json 항목에 "id"와 "pw" 필드가 필요합니다.')

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
        """에러 직전 스크린샷 캡처 (Death Cam)."""
        if not self._page:
            return
        try:
            fname = f"error_screenshot_{int(time.time())}.png"
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

            if log:
                mode = "Headless" if self._headless else "Visible"
                log(f"[POSTER] ✅ 브라우저 시작 완료 ({mode} Mode, UA: {ua[:40]}...)")
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 브라우저 시작 실패: {str(e)[:100]}")
            raise

    async def close_browser(self, log: Optional[Callable] = None) -> None:
        """브라우저 종료."""
        if log:
            log("[POSTER] 🔒 브라우저 종료 중...")

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
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
            await page.wait_for_timeout(1500)
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 로그인 페이지 로드 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] ⌨️ 아이디 입력 중 (visible + fill)...")

        try:
            id_input = page.locator(
                "input[placeholder='식별 코드'], #user_id"
            ).locator("visible=true").first
            await id_input.click()
            await id_input.fill(user_id)
            await page.wait_for_timeout(300)
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 아이디 셀렉터 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] ⌨️ 비밀번호 입력 중 (visible + fill)...")

        try:
            pw_input = page.locator(
                "input[placeholder='비밀번호'], input[type='password']"
            ).locator("visible=true").first
            await pw_input.click()
            await pw_input.fill(password)
            await page.wait_for_timeout(300)
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
            await page.wait_for_timeout(3000)
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

        # ── WAF 우회: 로그인 후 세션 안정화 딜레이 ──
        waf_delay = random.randint(2000, 4000)
        if log:
            log(f"[POSTER] ☕ 로그인 후 세션 안정화를 위해 잠시 대기 중... ({waf_delay}ms)")
        await page.wait_for_timeout(waf_delay)

        # 글쓰기 페이지 이동
        write_url = WRITE_URL_PATTERNS.get(
            self._gallery_type, WRITE_URL_PATTERNS["mgallery"]
        ).format(gallery_id=gallery_id)

        if log:
            log(f"[POSTER] 📄 글쓰기 페이지 이동 중... ({self._gallery_type}/{gallery_id})")

        try:
            await page.goto(write_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            if log:
                log(f"[POSTER] [ERROR] 글쓰기 페이지 로드 실패: {str(e)[:100]}")
            await self._take_death_cam(log)
            return False

        if log:
            log("[POSTER] ✍️ 갤러리 글쓰기 페이지 로드 완료")

        # 제목 입력
        if log:
            log(f"[POSTER] 📝 제목 입력 중: '{title[:30]}...'")

        try:
            subject_input = page.locator("#subject")
            await subject_input.click()
            await subject_input.type(title, delay=80)
            await page.wait_for_timeout(500)
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

        # ── 🖼️ 미끼 짤방: paste 이벤트 시뮬레이션 ──
        try:
            if log:
                log("[POSTER] 🖼️ 1x1 미끼 짤방 붙여넣기 시뮬레이션 중...")

            paste_js = """
            (el) => {
                const b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
                const bin = atob(b64);
                const arr = new Uint8Array(bin.length);
                for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
                const blob = new Blob([arr], {type: 'image/png'});
                const file = new File([blob], 'bait.png', {type: 'image/png'});

                const dt = new DataTransfer();
                dt.items.add(file);

                const event = new ClipboardEvent('paste', {
                    clipboardData: dt,
                    bubbles: true,
                    cancelable: true
                });
                el.dispatchEvent(event);
            }
            """
            await page.evaluate(paste_js, editor)
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

        try:
            await page.keyboard.type(content, delay=100)
            await page.wait_for_timeout(1000)
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

        try:
            submit_btn = page.locator(".btn_blue.btn_svc.write")
            await submit_btn.click()
            await page.wait_for_timeout(3000)
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
