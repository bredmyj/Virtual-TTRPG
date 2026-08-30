@echo off
setlocal
cd /d "%~dp0"
title Create shortcut

rem  Makes the double-click icon for this app, and offers to put one on the
rem  desktop as well. Run this again if the folder is ever moved - a
rem  shortcut remembers where its target was, so moving the folder leaves
rem  the old one pointing at nothing.

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo.
    echo   This needs Python, which is not installed on this PC.
    echo   Run the launcher instead - it will explain how to get it.
    echo.
    pause
    exit /b 1
)

echo.
choice /c YN /n /d N /t 60 /m "   Put a shortcut on the desktop too? [Y/N] "
if errorlevel 2 (
    %PY% "make_shortcut.py"
) else (
    %PY% "make_shortcut.py" --desktop
)

echo.
pause
