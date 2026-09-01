@echo off
rem  The server. One person runs this - whoever is willing to forward a
rem  port once - and everybody else adds its address to their server list.
rem
rem  It prints the addresses to hand round. Ctrl-C stops it, and every
rem  session on it ends with it.
setlocal
title Bredmyj's VTT - Server
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

%PY% server.py %*
echo.
pause
