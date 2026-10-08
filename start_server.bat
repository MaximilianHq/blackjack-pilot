@echo off
title Blackjack Pilot - AI Server Engine
cd /d "%~dp0"

echo ========================================================
echo       Blackjack Pilot - Local AI Server Launcher
echo       GitHub: https://github.com/MaximilianHq/blackjack-pilot
echo ========================================================
echo.

:: 1. Kontrollera om Python ar installerat
python --version >nul 2>&1
if errorlevel 1 goto :no_python

:: 2. Kontrollera om biblioteken finns
python -c "import ultralytics, websockets, torch" >nul 2>&1
if errorlevel 1 goto :install_deps

:run_server
:: 3. Registrera Native Messaging i Chrome/Edge
if exist "native_host\register_host.py" (
    python native_host\register_host.py >nul 2>&1
)

:: 4. Starta Blackjack Pilot AI Engine
echo [OK] Startar Blackjack Pilot AI Server pa ws://127.0.0.1:8765...
echo Lat detta fonster vara oppet medan du spelar pa casinot.
echo.

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
goto :run_server

:no_python
echo [!] Python hittades inte pa datorn!
echo Forsoker installera Python automatiskt via Windows...
winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo.
    echo [X] Kunde inte installera Python automatiskt.
    echo Vanligen ladda ner Python manuellt fran https://www.python.org/downloads/
    echo Kom ihag att kryssa i Add python.exe to PATH vid installationen.
    pause
    exit /b 1
)
echo.
echo [OK] Python har installerats. Starta om start_server.bat for att fortsatta.
pause
exit /b 0
