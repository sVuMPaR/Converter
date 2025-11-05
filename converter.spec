# converter.spec
# Пример spec-файла для PyInstaller. Можно использовать, если хотите тонко настроить сборку.
# Скопируйте в converter.spec и запустите: pyinstaller converter.spec

# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = collect_data_files('PIL') + collect_data_files('PyQt5')
hiddenimports = collect_submodules('PIL') + collect_submodules('PyQt5')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    name='converter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='assets/icon.ico'
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='converter'
)
