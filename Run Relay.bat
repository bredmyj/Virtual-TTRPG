@echo off
rem  The middleman. One person runs this - whoever has the most ordinary
rem  home connection - and everybody else dials out to it, the person
rem  running the game included.
rem
rem  It sets itself up, then prints the address to tell everyone.
setlocal
title Bredmyj's VTT - Relay
cd /d "%~dp0"

set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
    echo.
    echo   Python is not installed on this computer.
    echo   Get it from https://www.python.org/downloads/
    echo   Tick "Add python.exe to PATH" while installing.
    echo.
    pause
    exit /b 1
)

%PY% relay.py %*
echo.
pause
