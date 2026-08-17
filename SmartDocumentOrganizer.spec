# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

rapid_datas, rapid_binaries, rapid_hidden = collect_all("rapidocr")
onnx_datas, onnx_binaries, onnx_hidden = collect_all("onnxruntime")

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=rapid_binaries + onnx_binaries,
    datas=rapid_datas + onnx_datas + [("src/smartdoc/style.qss", "smartdoc")],
    hiddenimports=rapid_hidden + onnx_hidden + ["smartdoc"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartDocumentOrganizer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SmartDocumentOrganizer",
)
