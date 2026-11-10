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
    echo Не найден Python 3.9+. Установите с https://www.python.org/downloads/ и отметьте "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
    echo Создаю окружение сборки .build-venv ...
    %PY% -m venv .build-venv || goto :error
)
call ".build-venv\Scripts\activate.bat"
python -m pip install --disable-pip-version-check -r requirements-build.txt || goto :error
python packaging\build_app.py || goto :error

echo.
echo Готово: %CD%\dist\StardewTracker.exe
pause
exit /b 0

:error
echo.
echo Сборка не удалась. Скопируйте текст ошибки выше.
pause
exit /b 1
