@echo off
setlocal enabledelayedexpansion
title Bredmyj's VTT
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem  If the app has been built into a program, there is nothing to set
rem  up - just run it.
rem ------------------------------------------------------------------
if exist "Bredmyj's VTT.exe" (
    start "" "Bredmyj's VTT.exe"
    exit /b 0
)

rem ------------------------------------------------------------------
rem  Otherwise it needs Python. Try the launcher first, since that is
rem  what a normal install leaves behind, then the plain command.
rem ------------------------------------------------------------------
set "PY="
set "PYW="
py -3 --version >nul 2>&1 && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY (
    python --version >nul 2>&1 && (set "PY=python" & set "PYW=pythonw")
)

if not defined PY (
    echo.
    echo   Bredmyj's VTT needs Python, and it is not installed on this PC.
    echo.
    echo   1. Go to        https://www.python.org/downloads/
    echo   2. Download Python for Windows and run the installer.
    echo   3. IMPORTANT: tick "Add python.exe to PATH" on the first screen.
    echo   4. Finish the install, then run this file again.
    echo.
    echo   It is a normal, safe install and takes about two minutes.
    echo.
    choice /c YN /n /d N /t 60 /m "   Open the download page now? [Y/N] "
    if !errorlevel! equ 1 start "" "https://www.python.org/downloads/"
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem  Tkinter is what draws the windows. It comes with Python, but some
rem  cut-down installs leave it out, and without it nothing can open.
rem ------------------------------------------------------------------
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   This copy of Python is missing Tkinter, which draws the windows.
    echo.
    echo   The installer from python.org includes it. If you installed
    echo   Python from the Microsoft Store or somewhere else, install it
    echo   from python.org instead and run this again.
    echo.
    pause
    exit /b 1
)

rem ------------------------------------------------------------------
rem  Pillow is only needed for pictures - profile photos, portraits and
rem  the coloured pointer. Everything else works without it, so this is
rem  an offer rather than a demand.
rem ------------------------------------------------------------------
%PY% -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   One optional extra is missing: Pillow.
    echo.
    echo   Without it the app still runs - dice, journal, map, and playing
    echo   with other people all work. What you lose is pictures: profile
    echo   photos, character portraits, and the coloured mouse pointer.
    echo.
    choice /c YN /n /d N /t 60 /m "   Install it now? It takes a few seconds. [Y/N] "
    if !errorlevel! equ 1 (
        echo.
        echo   Installing Pillow...
        %PY% -m pip install --upgrade pillow
        if errorlevel 1 (
            echo.
            echo   That did not work. The app will still open, just without
            echo   pictures. You can try again later from a command prompt:
            echo       python -m pip install pillow
            echo.
            pause
        )
    )
)

rem ------------------------------------------------------------------
rem  pythonw runs it without leaving a black console window behind.
rem ------------------------------------------------------------------
start "" %PYW% "dice_roller.py"
exit /b 0
