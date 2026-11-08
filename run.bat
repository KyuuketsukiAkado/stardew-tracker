@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%~dp0tracker.py" serve %*
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python "%~dp0tracker.py" serve %*
    ) else (
        echo Не найден Python 3.9+. Установите с https://www.python.org/downloads/ и отметьте "Add python.exe to PATH".
        pause
        exit /b 1
    )
)
if errorlevel 1 (
    echo.
    pause
)
