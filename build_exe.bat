@echo off
echo ===============================================
echo Ghost Protocol - Build Executable
echo ===============================================
echo.

REM 가상환경 활성화 (있다면)
if exist venv\Scripts\activate.bat (
    echo [1/4] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [!] No virtual environment found. Using system Python.
)

echo.
echo [2/4] Installing PyInstaller...
pip install pyinstaller

echo.
echo [3/4] Building executable...
pyinstaller --name="GhostProtocol" ^
            --onefile ^
            --windowed ^
            --icon=NONE ^
            --add-data="ghost_protocol;ghost_protocol" ^
            --hidden-import=textual ^
            --hidden-import=playwright ^
            --hidden-import=pandas ^
            --hidden-import=rich ^
            --collect-all=textual ^
            --collect-all=playwright ^
            main.py

echo.
echo [4/4] Cleaning up...
REM dist 폴더로 data 디렉토리 복사
if not exist dist\data mkdir dist\data

echo.
echo ===============================================
echo BUILD COMPLETE!
echo ===============================================
echo Executable: dist\GhostProtocol.exe
echo.
echo IMPORTANT: Before running, execute:
echo   playwright install chromium
echo.
pause
