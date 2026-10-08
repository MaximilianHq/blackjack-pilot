@echo off
title Blackjack Pilot - AI Server Engine
cd /d "%~dp0"
echo ========================================================
echo       Blackjack Pilot - Local AI Server Launcher
echo       GitHub: https://github.com/MaximilianHq/blackjack-pilot
echo ========================================================
echo.

:: Automatically register Native Messaging host in Chrome/Edge registry
if exist "native_host\register_host.py" (
    python native_host\register_host.py >nul 2>&1
)

echo Starting Blackjack Pilot AI Server on ws://127.0.0.1:8765...
echo (Keep this window open while playing)
echo.

python -u server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ========================================================
    echo Server stopped with error code %ERRORLEVEL%.
    echo If libraries are missing, run: pip install -r requirements.txt
    echo ========================================================
    pause
)

