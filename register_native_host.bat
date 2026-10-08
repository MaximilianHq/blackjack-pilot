@echo off
cd /d "%~dp0"
echo =======================================================
echo   Blackjack Pilot - Register Server Launcher in Chrome
echo =======================================================
echo.
python native_host\register_host.py %*
echo.
pause

