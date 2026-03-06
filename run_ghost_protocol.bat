@echo off
chcp 65001 >nul 2>&1

:: =====================================================
::  GHOST PROTOCOL v5.0  LAUNCHPAD EDITION
::  Debug-enabled: all output logged to launcher_debug.log
:: =====================================================

:: -- 로그 파일 초기화 --------------------------------
set "LOG=%~dp0launcher_debug.log"
echo [%DATE% %TIME%] ===== GHOST PROTOCOL LAUNCHER START ===== > "%LOG%"

:: -- 프로젝트 루트로 강제 이동 -----------------------
cd /d "%~dp0"
echo [%DATE% %TIME%] CWD: %CD% >> "%LOG%"

:: -- 가상환경 자동 활성화 ----------------------------
if exist ".venv\Scripts\activate.bat" (
    echo [%DATE% %TIME%] Activating .venv... >> "%LOG%"
    call ".venv\Scripts\activate.bat" >> "%LOG%" 2>&1
    echo [INFO] .venv activated. >> "%LOG%"
    echo [INFO] .venv virtual environment activated.
) else if exist "venv\Scripts\activate.bat" (
    echo [%DATE% %TIME%] Activating venv... >> "%LOG%"
    call "venv\Scripts\activate.bat" >> "%LOG%" 2>&1
    echo [INFO] venv activated. >> "%LOG%"
    echo [INFO] venv virtual environment activated.
) else (
    echo [WARN] No virtual environment found. Using system Python. >> "%LOG%"
)

cls
echo.
echo  =====================================================
echo.
echo     ______  __  __  ____  ___  ____    ____  ____
echo    / ____/ / / / / / __ \/  / / __/   / __ \/ __ \
echo   / / __  / /_/ / / / / /  / _\ \    / /_/ / /_/ /
echo  / /_/ / / __  / / /_/ /  / /___/   / ____/ _, _/
echo  \____/ /_/ /_/  \____/  /____/    /_/   /_/ ^|_^|
echo.
echo       v5.0  LAUNCHPAD EDITION  -  SWARM MODE
echo.
echo  =====================================================
echo.
echo   Project Root : %CD%
echo   Entry Point  : app.py
echo   Framework    : Streamlit
echo   Debug Log    : %LOG%
echo.
echo  =====================================================
echo.

:: -- 환경 정보 로깅 ----------------------------------
echo [%DATE% %TIME%] --- Environment Info --- >> "%LOG%"
echo [INFO] python path: >> "%LOG%"
where python >> "%LOG%" 2>&1
echo [INFO] streamlit path: >> "%LOG%"
where streamlit >> "%LOG%" 2>&1
echo [INFO] streamlit version check: >> "%LOG%"
pip list 2>&1 | findstr /i "streamlit" >> "%LOG%"

:: -- Streamlit 확인 ----------------------------------
where streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] streamlit not found in PATH. >> "%LOG%"
    echo  [ERROR] streamlit command not found.
    echo  Run: pip install streamlit
    echo.
    pause
    exit /b 1
)

:: -- Python 확인 -------------------------------------
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] python not found in PATH. >> "%LOG%"
    echo  [ERROR] Python not found in PATH.
    echo.
    pause
    exit /b 1
)

:: -- app.py 존재 확인 ---------------------------------
if not exist "app.py" (
    echo [ERROR] app.py not found. CWD: %CD% >> "%LOG%"
    echo  [ERROR] app.py not found in: %CD%
    echo.
    pause
    exit /b 1
)

:: -- 실행 --------------------------------------------
echo [%DATE% %TIME%] All checks passed. Launching Streamlit... >> "%LOG%"
echo  Launching Ghost Protocol...
echo.

streamlit run app.py 2>> "%LOG%"
set "EXIT_CODE=%errorlevel%"

echo [%DATE% %TIME%] Streamlit exited. Exit code: %EXIT_CODE% >> "%LOG%"
echo.
echo  Ghost Protocol exited. Debug log: %LOG%
pause
