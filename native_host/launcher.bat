@echo off
if exist "%~dp0BlackjackHost.exe" (
    "%~dp0BlackjackHost.exe" %*
) else (
    python -u "%~dp0host.py" %*
)
