"""Ghost Protocol Web Edition - EXE Build Script.

launcher.py를 PyInstaller로 빌드한 후,
app.py + ghost_protocol/ 패키지를 dist/ 폴더에 복사하여
원클릭 실행 가능한 배포 패키지를 생성.

사용법: python build_web_exe.py
결과물: dist/GhostProtocol/ (폴더 배포)
         - GhostProtocol.exe  (런처)
         - app.py             (Streamlit 앱)
         - ghost_protocol/    (크롤러 패키지)
"""

import subprocess
import sys
import os
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LAUNCHER = os.path.join(PROJECT_DIR, "launcher.py")
DIST_DIR = os.path.join(PROJECT_DIR, "dist", "GhostProtocol")


def build():
    print("=" * 60)
    print("  GHOST PROTOCOL Web - EXE BUILD")
    print("=" * 60)
    print()

    # Step 1: PyInstaller로 launcher.exe 빌드 (onefile)
    print("  [1/3] Building launcher EXE...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", "GhostProtocol",
        "--noconfirm",
        "--clean",
        LAUNCHER,
    ]

    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    if result.returncode != 0:
        print("\n  BUILD FAILED")
        sys.exit(1)

    # Step 2: dist/GhostProtocol/ 폴더 구성
    print()
    print("  [2/3] Creating deployment package...")

    # onefile 빌드 결과는 dist/GhostProtocol.exe
    onefile_exe = os.path.join(PROJECT_DIR, "dist", "GhostProtocol.exe")
    if not os.path.exists(onefile_exe):
        print(f"  ERROR: {onefile_exe} not found")
        sys.exit(1)

    # dist/GhostProtocol/ 폴더 생성
    if os.path.exists(DIST_DIR):
        shutil.rmtree(DIST_DIR)
    os.makedirs(DIST_DIR, exist_ok=True)

    # EXE 이동
    shutil.move(onefile_exe, os.path.join(DIST_DIR, "GhostProtocol.exe"))

    # app.py 복사
    shutil.copy2(
        os.path.join(PROJECT_DIR, "app.py"),
        os.path.join(DIST_DIR, "app.py"),
    )

    # ghost_protocol/ 패키지 복사
    src_pkg = os.path.join(PROJECT_DIR, "ghost_protocol")
    dst_pkg = os.path.join(DIST_DIR, "ghost_protocol")
    if os.path.exists(dst_pkg):
        shutil.rmtree(dst_pkg)
    shutil.copytree(
        src_pkg, dst_pkg,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    # data/ 디렉토리 생성 (DB/CSV 저장용)
    os.makedirs(os.path.join(DIST_DIR, "data"), exist_ok=True)

    # Step 3: 결과 확인
    print("  [3/3] Verifying package...")
    print()

    exe_path = os.path.join(DIST_DIR, "GhostProtocol.exe")
    exe_size = os.path.getsize(exe_path) / (1024 * 1024)

    total_size = 0
    file_count = 0
    for root, dirs, files in os.walk(DIST_DIR):
        for f in files:
            fp = os.path.join(root, f)
            total_size += os.path.getsize(fp)
            file_count += 1

    total_mb = total_size / (1024 * 1024)

    print("=" * 60)
    print("  BUILD SUCCESS")
    print("=" * 60)
    print()
    print(f"  Output:    {DIST_DIR}")
    print(f"  EXE Size:  {exe_size:.1f} MB")
    print(f"  Total:     {total_mb:.1f} MB ({file_count} files)")
    print()
    print("  Package contents:")
    print(f"    GhostProtocol.exe   <- Double-click to run!")
    print(f"    app.py              <- Streamlit dashboard")
    print(f"    ghost_protocol/     <- Crawler engine")
    print(f"    data/               <- DB & CSV output")
    print()
    print("  Requirements (auto-installed on first run):")
    print("    - Python 3.10+ must be in system PATH")
    print("    - pip packages: streamlit, playwright, pandas, plotly")
    print("    - Playwright Chromium browser")
    print()
    print("  All requirements are automatically checked and")
    print("  installed when you run GhostProtocol.exe!")
    print("=" * 60)


if __name__ == "__main__":
    build()
