@echo off
chcp 65001 >nul 2>&1
title Ghost Protocol v5.0 — Launchpad

:: ═══════════════════════════════════════════════════════════
::  GHOST PROTOCOL v5.0  ·  LAUNCHPAD EDITION
::  One-click launcher — always starts from project root
:: ═══════════════════════════════════════════════════════════

:: ── 프로젝트 루트로 강제 이동 ──────────────────────────────
:: 배치 파일 위치를 기준으로 경로를 결정 (dist/ 등 어디서 실행해도 안전)
cd /d "%~dp0"

:: ── 시작 배너 ──────────────────────────────────────────────
cls
echo.
echo  =====================================================
echo.
echo     ______  __  __  ____  ___  ____    ____  ____
echo    / ____/ / / / / / __ \/  / / __/   / __ \/ __ \
echo   / / __  / /_/ / / / / /  / _\ \    / /_/ / /_/ /
echo  / /_/ / / __  / / /_/ /  / /___/   / ____/ _, _/
echo  \____/ /_/ /_/  \____/  /____/    /_/   /_/ |_|
echo.
echo       v5.0  LAUNCHPAD EDITION  ·  SWARM MODE
echo.
echo  =====================================================
echo.
echo   Project Root : %CD%
echo   Entry Point  : app.py
echo   Framework    : Streamlit
echo.
echo  =====================================================
echo.

:: ── Python / Streamlit 확인 ────────────────────────────────
where streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] streamlit 명령어를 찾을 수 없습니다.
    echo  가상환경이 활성화되어 있는지 확인하거나
    echo  pip install streamlit 을 먼저 실행하세요.
    echo.
    pause
    exit /b 1
)

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Python이 설치되어 있지 않거나 PATH에 없습니다.
    echo.
    pause
    exit /b 1
)

:: ── app.py 존재 확인 ────────────────────────────────────────
if not exist "app.py" (
    echo  [ERROR] app.py를 현재 디렉토리에서 찾을 수 없습니다.
    echo  현재 경로: %CD%
    echo.
    pause
    exit /b 1
)

:: ── 실행 ────────────────────────────────────────────────────
echo  Launching Ghost Protocol...
echo.
streamlit run app.py

:: ── 종료 후 대기 (에러 메시지 확인용) ─────────────────────
echo.
echo  Ghost Protocol이 종료되었습니다.
pause
