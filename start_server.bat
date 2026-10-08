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
if %ERRORLEVEL% NEQ 0 (
    echo [!] Python hittades inte pa datorn!
    echo.
    echo Forsoker installera Python 3.11 automatiskt via Windows...
    winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [X] Kunde inte installera Python automatiskt.
        echo Vanligen installera Python manuellt fran: https://www.python.org/downloads/
        echo VIKTIGT: Kom ihag att kryssa i "Add python.exe to PATH" vid installationen!
        echo.
        pause
        exit /b 1
    )
    echo.
    echo [OK] Python har installerats! Starta om denna fil (start_server.bat) for att fortsatta.
    pause
    exit /b 0
)

:: 2. Kontrollera om biblioteken finns (ultralytics, torch, websockets)
python -c "import ultralytics, websockets, torch" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [!] Forsta korningen upptackt: Installerar nodvandiga AI-bibliotek...
    echo     Detta laddar ner PyTorch, YOLO och websockets (tar ca 1-3 minuter).
    echo.
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo.
        echo [X] Ett fel uppstod vid installation av kraven i requirements.txt.
        pause
        exit /b 1
    )
    echo.
    echo [OK] Alla bibliotek har installerats framgangsrikt!
    echo.
)

:: 3. Registrera Native Messaging i Chrome/Edge automatiskt
if exist "native_host\register_host.py" (
    python native_host\register_host.py >nul 2>&1
)

:: 4. Starta Blackjack Pilot AI Engine
echo [OK] Startar Blackjack Pilot AI Server pa ws://127.0.0.1:8765...
echo (Lat detta fonster vara oppet medan du spelar pa casinot)
echo.

python -u server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Servern stangdes av.
    pause
)
