# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-сборка standalone-приложения StardewTracker.

Запуск из корня репозитория:
    python packaging/build_app.py

Получается один файл dist/StardewTracker (dist/StardewTracker.exe в Windows),
внутри — пакет stardew_tracker, data/ и assets/.
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent

a = Analysis(
    [str(ROOT / "tracker.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "data"), "data"),
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Стандартная библиотека нужна целиком: сервер тянет http/email/socket.
    excludes=["tkinter", "unittest", "doctest", "pdb", "pytest"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="StardewTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
