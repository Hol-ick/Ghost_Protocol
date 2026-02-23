"""Ghost Protocol Web - One-Click Launcher.

이 스크립트를 PyInstaller로 빌드하면 GhostProtocol.exe가 되며,
실행 시 자동으로:
  1. 시스템 Python 탐색
  2. 필수 패키지 확인/설치
  3. Playwright 브라우저 확인/설치
  4. Streamlit 서버 구동
  5. 브라우저 자동 열기
"""

import os
import sys
import subprocess
import shutil
import time
import webbrowser
import threading

# ── 경로 설정 ──
if getattr(sys, 'frozen', False):
    # PyInstaller EXE: exe가 있는 폴더
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_FILE = os.path.join(BASE_DIR, "app.py")
GHOST_PKG = os.path.join(BASE_DIR, "ghost_protocol")
PORT = 8501

# ── 콘솔 색상 (Windows ANSI) ──
os.system("")  # Windows 10+ ANSI escape 활성화

GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ── 시스템 Python 경로 (EXE 내에서는 sys.executable이 EXE 자체를 가리킴) ──
PYTHON_EXE = None


def find_system_python():
    """시스템에 설치된 Python 3.10+ 경로를 탐색."""
    global PYTHON_EXE

    # 1) EXE가 아니면 현재 Python 사용
    if not getattr(sys, 'frozen', False):
        PYTHON_EXE = sys.executable
        return True

    # 2) PATH에서 python 찾기
    candidates = ["python", "python3"]
    for name in candidates:
        path = shutil.which(name)
        if path:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    ver = result.stdout.strip()  # "Python 3.13.1"
                    parts = ver.split()
                    if len(parts) >= 2:
                        nums = parts[1].split(".")
                        major, minor = int(nums[0]), int(nums[1])
                        if major >= 3 and minor >= 10:
                            PYTHON_EXE = path
                            return True
            except Exception:
                continue

    # 3) 일반적인 Windows 설치 경로 탐색
    common_paths = [
        r"C:\Python313\python.exe",
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python313\python.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python312\python.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python311\python.exe"),
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python310\python.exe"),
    ]
    for p in common_paths:
        if os.path.exists(p):
            PYTHON_EXE = p
            return True

    return False


def banner():
    print(f"""{GREEN}
  =============================================
   {BOLD}GHOST PROTOCOL v0.3 - Web Edition{RESET}{GREEN}
  =============================================
   DC Inside Community Opinion Analyzer
   Powered by Streamlit + Playwright
  ============================================={RESET}
""")


def check_python():
    """Python 탐색 및 버전 확인."""
    print(f"  {CYAN}[CHECK]{RESET} Searching for Python...", end="")
    if find_system_python():
        # 버전 출력
        try:
            result = subprocess.run(
                [PYTHON_EXE, "--version"],
                capture_output=True, text=True, timeout=10
            )
            ver = result.stdout.strip()
            print(f"  {GREEN}{ver} at {PYTHON_EXE}{RESET}")
        except Exception:
            print(f"  {GREEN}Found: {PYTHON_EXE}{RESET}")
        return True
    else:
        print(f"  {RED}NOT FOUND{RESET}")
        print(f"  {RED}[ERROR]{RESET} Python 3.10+ is required but not found in PATH.")
        print(f"  {RED}        Please install Python from https://python.org{RESET}")
        return False


def check_package_via_pip(name):
    """pip show으로 패키지 설치 여부 확인."""
    try:
        result = subprocess.run(
            [PYTHON_EXE, "-m", "pip", "show", name],
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except Exception:
        return False


def install_packages():
    """필수 패키지 설치."""
    packages = ["streamlit", "plotly", "playwright", "pandas", "rich"]

    missing = []
    for pkg in packages:
        status = check_package_via_pip(pkg)
        label = f"{GREEN}OK{RESET}" if status else f"{YELLOW}MISSING{RESET}"
        print(f"  {CYAN}[CHECK]{RESET} {pkg:20s} {label}")
        if not status:
            missing.append(pkg)

    if missing:
        print()
        print(f"  {YELLOW}[INSTALL]{RESET} Installing: {', '.join(missing)}")
        cmd = [PYTHON_EXE, "-m", "pip", "install"] + missing + ["-q"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  {RED}[ERROR]{RESET} pip install failed:")
            print(result.stderr[:500])
            return False
        print(f"  {GREEN}[OK]{RESET} All packages installed")

    return True


def check_playwright_browser():
    """Playwright Chromium 브라우저 설치 확인."""
    print()
    print(f"  {CYAN}[CHECK]{RESET} Playwright Chromium browser...", end="")

    home = os.path.expanduser("~")
    pw_path = os.path.join(home, "AppData", "Local", "ms-playwright")

    chromium_found = False
    if os.path.exists(pw_path):
        for d in os.listdir(pw_path):
            if d.startswith("chromium-") or d.startswith("chromium_headless"):
                chromium_found = True
                break

    if chromium_found:
        print(f"  {GREEN}OK{RESET}")
        return True

    print(f"  {YELLOW}NOT FOUND{RESET}")
    print(f"  {YELLOW}[INSTALL]{RESET} Installing Chromium (~100MB download)...")
    result = subprocess.run(
        [PYTHON_EXE, "-m", "playwright", "install", "chromium"],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        print(f"  {RED}[ERROR]{RESET} Chromium install failed")
        print(result.stderr[:500])
        return False
    print(f"  {GREEN}[OK]{RESET} Chromium installed")
    return True


def check_app_file():
    """app.py 존재 확인."""
    print(f"  {CYAN}[CHECK]{RESET} app.py", end="")
    if os.path.exists(APP_FILE):
        print(f"                    {GREEN}OK{RESET}")
        return True
    else:
        print(f"                    {RED}NOT FOUND{RESET}")
        print(f"  {RED}[ERROR]{RESET} {APP_FILE}")
        return False


def check_ghost_package():
    """ghost_protocol 패키지 확인."""
    print(f"  {CYAN}[CHECK]{RESET} ghost_protocol/", end="")
    if os.path.isdir(GHOST_PKG):
        print(f"             {GREEN}OK{RESET}")
        return True
    else:
        print(f"             {RED}NOT FOUND{RESET}")
        return False


def open_browser_delayed():
    """Streamlit 서버 준비될 때까지 대기 후 브라우저 열기."""
    import urllib.request
    url = f"http://localhost:{PORT}"

    for _ in range(30):  # 최대 30초 대기
        time.sleep(1)
        try:
            urllib.request.urlopen(url, timeout=2)
            print(f"\n  {GREEN}[BROWSER]{RESET} Opening {url}")
            webbrowser.open(url)
            return
        except Exception:
            continue

    # 타임아웃이어도 한번 시도
    print(f"\n  {YELLOW}[BROWSER]{RESET} Opening {url} (server may still be loading)")
    webbrowser.open(url)


def run_streamlit():
    """Streamlit 서버 실행."""
    print(f"""
  {GREEN}=============================================
   SERVER STARTING
  ============================================={RESET}
  {DIM}URL: http://localhost:{PORT}
  Press Ctrl+C to stop{RESET}
""")

    # 브라우저 자동 열기 (별도 스레드)
    t = threading.Thread(target=open_browser_delayed, daemon=True)
    t.start()

    # Streamlit 실행 — 시스템 Python 사용
    cmd = [
        PYTHON_EXE, "-m", "streamlit", "run", APP_FILE,
        "--server.port", str(PORT),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--theme.base", "dark",
        "--theme.primaryColor", "#00ff41",
        "--theme.backgroundColor", "#0a0a0a",
        "--theme.secondaryBackgroundColor", "#0d1117",
        "--theme.textColor", "#ffffff",
    ]

    try:
        proc = subprocess.Popen(cmd, cwd=BASE_DIR)
        proc.wait()
    except KeyboardInterrupt:
        print(f"\n  {YELLOW}[STOP]{RESET} Shutting down...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print(f"  {GREEN}[OK]{RESET} Server stopped")


def main():
    banner()

    print(f"  {BOLD}Pre-flight checks:{RESET}")
    print()

    # 체크 시퀀스
    if not check_python():
        input("\n  Press Enter to exit...")
        sys.exit(1)

    if not check_app_file():
        input("\n  Press Enter to exit...")
        sys.exit(1)

    if not check_ghost_package():
        input("\n  Press Enter to exit...")
        sys.exit(1)

    if not install_packages():
        input("\n  Press Enter to exit...")
        sys.exit(1)

    if not check_playwright_browser():
        input("\n  Press Enter to exit...")
        sys.exit(1)

    print(f"\n  {GREEN}{BOLD}All checks passed!{RESET}")

    # Streamlit 실행
    run_streamlit()


if __name__ == "__main__":
    main()
