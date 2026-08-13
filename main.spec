# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the D2R Infernal Auto Potion tool.
# Build:  pyinstaller main.spec --noconfirm
# Output: dist/D2RAutoPotion.exe  (single file, no console window)

from PyInstaller.utils.hooks import collect_all

# customtkinter ships JSON theme data and submodules that must be bundled.
datas, binaries, hiddenimports = collect_all('customtkinter')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'matplotlib', 'pandas', 'PIL', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='D2RAutoPotion',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
