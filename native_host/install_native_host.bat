@echo off
title Blackjack Pilot - Host Installer
cd /d "%~dp0"

echo ========================================================
echo   Registrerar Blackjack Pilot i Chrome & Edge...
echo ========================================================
echo.

if exist "BlackjackHost.exe" (
    "BlackjackHost.exe" --register
) else (
    python register_host.py
)

echo.
echo [OK] Klart! Du kan nu klicka pa "Starta Server" direkt i Chrome-appen.
timeout /t 3 >nul
exit /b 0

