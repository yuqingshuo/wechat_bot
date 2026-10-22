@echo off
rem Launcher: pure ASCII on purpose.
rem All user messages live in boot.py because cmd.exe mis-parses
rem UTF-8 Chinese batch lines on GBK consoles (even with chcp 65001).
setlocal EnableExtensions
cd /d "%~dp0"
set "PY="
where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [ERROR] Python 3.9+ not found. Install from https://www.python.org/downloads/
    pause
    exit /b 1
)
%PY% boot.py %*
exit /b %ERRORLEVEL%
