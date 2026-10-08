@echo off
title Blackjack Pilot - AI Server Engine
cd /d "%~dp0"

echo ========================================================
echo       Blackjack Pilot - Local AI Server Launcher
echo       GitHub: https://github.com/MaximilianHq/blackjack-pilot
echo ========================================================
echo.

:: 0. Registrera Chrome/Edge Native Messaging automatiskt om host finns
if exist "native_host\BlackjackHost.exe" (
    "native_host\BlackjackHost.exe" --register >nul 2>&1
)

:: 1. Om standalone EXE finns i dist eller root, starta den direkt (NO PYTHON NEEDED!)
if exist "BlackjackPilotServer.exe" (
    echo [OK] Standalone AI Engine hittad. Startar server...
    start "Blackjack Pilot AI Server" "BlackjackPilotServer.exe"
    exit /b 0
)

if exist "dist\BlackjackPilotServer\BlackjackPilotServer.exe" (
    echo [OK] Standalone AI Engine hittad. Startar server...
    start "Blackjack Pilot AI Server" "dist\BlackjackPilotServer\BlackjackPilotServer.exe"
    exit /b 0
)

:: 2. Fallback: For utvecklare med Python installerat
python --version >nul 2>&1
if errorlevel 1 goto :no_python

python -c "import ultralytics, websockets, torch" >nul 2>&1
if errorlevel 1 goto :install_deps

:run_python_server
echo [OK] Startar Blackjack Pilot AI Server pa ws://127.0.0.1:8765 via Python...
python -u server.py
if errorlevel 1 (
    echo.
    echo Servern stangdes av.
    pause
)
exit /b 0

:install_deps
echo [!] Forsta korningen: Installerar nodvandiga AI-bibliotek...
echo     Detta laddar ner PyTorch, YOLO och websockets.
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [X] Ett fel uppstod vid installation av kraven.
    pause
    exit /b 1
)
echo.
echo [OK] Alla bibliotek har installerats!
goto :run_python_server

:no_python
echo [!] Varken BlackjackPilotServer.exe eller Python hittades pa datorn!
echo Ladda ner fardiga Windows-paketet fran GitHub Releases:
echo https://github.com/MaximilianHq/blackjack-pilot/releases
echo.
pause
exit /b 1
