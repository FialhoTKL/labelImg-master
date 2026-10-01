# -*- mode: python ; coding: utf-8 -*-
# Build do LabelImg (modo pasta / onedir), empacotado depois pelo Inno Setup
# (installer/labelimg.iss). Antes, gerar libs/resources.py:
#   pyrcc5 -o libs/resources.py resources.qrc
#   pyinstaller labelImg.spec --noconfirm


a = Analysis(
    ['labelImg.py'],
    pathex=['libs', '.'],
    binaries=[],
    datas=[('data', 'data')],
    hiddenimports=['xml', 'xml.etree', 'xml.etree.ElementTree', 'lxml.etree', 'lxml._elementpath'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LabelImg',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources\\icons\\app.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LabelImg',
)
