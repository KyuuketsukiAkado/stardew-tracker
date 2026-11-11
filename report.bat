@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo Python 3.9+ was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    echo Не найден Python 3.9+. Установите с https://www.python.org/downloads/ и отметьте "Add python.exe to PATH".
    pause
    exit /b 1
)

%PY% "%~dp0tracker.py" open %*
if errorlevel 1 pause
