"""Ghost Protocol - EXE 빌드 스크립트.

사용법: python build_exe.py
결과물: dist/GhostProtocol.exe (원클릭 실행 가능)
"""

import subprocess
import sys
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_SCRIPT = os.path.join(PROJECT_DIR, "main.py")

def find_package_path(package_name: str) -> str:
    """패키지의 설치 경로를 찾음."""
    import importlib
    mod = importlib.import_module(package_name)
    return mod.__path__[0]

def build():
    textual_path = find_package_path("textual")
    rich_path = find_package_path("rich")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",            # TUI이므로 콘솔 필요
        "--name", "GhostProtocol",

        # Textual 전체 패키지를 data로 포함 (CSS, 위젯 테마 등)
        "--add-data", f"{textual_path}{os.pathsep}textual",
        "--add-data", f"{rich_path}{os.pathsep}rich",

        # Hidden imports: Textual 내부 의존성
        "--hidden-import", "textual",
        "--hidden-import", "textual.app",
        "--hidden-import", "textual.binding",
        "--hidden-import", "textual.containers",
        "--hidden-import", "textual.widgets",
        "--hidden-import", "textual.widgets._button",
        "--hidden-import", "textual.widgets._data_table",
        "--hidden-import", "textual.widgets._footer",
        "--hidden-import", "textual.widgets._header",
        "--hidden-import", "textual.widgets._input",
        "--hidden-import", "textual.widgets._label",
        "--hidden-import", "textual.widgets._progress_bar",
        "--hidden-import", "textual.widgets._rich_log",
        "--hidden-import", "textual.widgets._static",
        "--hidden-import", "textual.widgets._switch",
        "--hidden-import", "textual.widgets._tabbed_content",
        "--hidden-import", "textual.widgets._tab_pane",
        "--hidden-import", "textual.css",
        "--hidden-import", "textual.css.query",
        "--hidden-import", "textual.dom",
        "--hidden-import", "textual.screen",
        "--hidden-import", "textual.driver",
        "--hidden-import", "textual.drivers",
        "--hidden-import", "textual.drivers.win32",
        "--hidden-import", "textual._xterm_parser",
        "--hidden-import", "textual._text_area_theme",
        "--hidden-import", "textual._types",
        "--hidden-import", "textual.events",
        "--hidden-import", "textual.message",
        "--hidden-import", "textual.reactive",
        "--hidden-import", "textual.timer",
        "--hidden-import", "textual.worker",
        "--hidden-import", "textual.command",
        "--hidden-import", "rich",
        "--hidden-import", "rich.text",
        "--hidden-import", "rich.markup",
        "--hidden-import", "rich.console",
        "--hidden-import", "rich.highlighter",
        "--hidden-import", "rich.traceback",
        "--hidden-import", "rich.pretty",
        "--hidden-import", "rich.syntax",
        "--hidden-import", "rich.theme",
        "--hidden-import", "rich.color",
        "--hidden-import", "rich.style",
        "--hidden-import", "rich.segment",
        "--hidden-import", "markdown_it",
        "--hidden-import", "linkify_it",
        "--hidden-import", "mdit_py_plugins",
        "--hidden-import", "pygments",
        "--hidden-import", "platformdirs",
        "--hidden-import", "sqlite3",
        "--hidden-import", "csv",
        "--hidden-import", "asyncio",

        # Playwright는 exe에 포함 불가 (외부 브라우저 바이너리 필요)
        # 대신 런타임에 시스템 설치된 playwright를 사용
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.async_api",
        "--hidden-import", "pyee",
        "--hidden-import", "greenlet",

        # ghost_protocol 패키지
        "--hidden-import", "ghost_protocol",
        "--hidden-import", "ghost_protocol.config",
        "--hidden-import", "ghost_protocol.database",
        "--hidden-import", "ghost_protocol.scraper",
        "--hidden-import", "ghost_protocol.ui",

        # 추가 옵션
        "--noconfirm",
        "--clean",

        MAIN_SCRIPT,
    ]

    print("=" * 60)
    print("  GHOST PROTOCOL - EXE BUILD")
    print("=" * 60)
    print()
    print(f"  Source:  {MAIN_SCRIPT}")
    print(f"  Output:  dist/GhostProtocol.exe")
    print()
    print("  Building... (this may take 1-2 minutes)")
    print()

    result = subprocess.run(cmd, cwd=PROJECT_DIR)

    if result.returncode == 0:
        exe_path = os.path.join(PROJECT_DIR, "dist", "GhostProtocol.exe")
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print()
            print("=" * 60)
            print(f"  BUILD SUCCESS")
            print(f"  Output: {exe_path}")
            print(f"  Size:   {size_mb:.1f} MB")
            print("=" * 60)
            print()
            print("  사전 요구사항:")
            print("    1. pip install playwright")
            print("    2. playwright install chromium")
            print()
            print("  실행: dist\\GhostProtocol.exe")
        else:
            print("  WARNING: Build succeeded but exe not found")
    else:
        print()
        print("  BUILD FAILED — check output above")
        sys.exit(1)


if __name__ == "__main__":
    build()
