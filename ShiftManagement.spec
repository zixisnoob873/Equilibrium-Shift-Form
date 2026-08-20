# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

BASE_DIR = os.path.abspath(SPECPATH)

added_datas = [
    (os.path.join(BASE_DIR, 'templates'), 'templates'),
    (os.path.join(BASE_DIR, 'static'), 'static'),
    (os.path.join(BASE_DIR, 'assets'), 'assets'),
]

hidden_imports = [
    'waitress',
    'waitress.adjustments',
    'waitress.buffers',
    'waitress.channel',
    'waitress.compat',
    'waitress.parser',
    'waitress.proxy_headers',
    'waitress.receiver',
    'waitress.runner',
    'waitress.server',
    'waitress.task',
    'waitress.trigger',
    'waitress.utilities',
    'waitress.wasyncore',
    'flask',
    'flask_cors',
    'flask_wtf',
    'flask_wtf.csrf',
    'flask_talisman',
    'jinja2',
    'werkzeug',
    'werkzeug.security',
    'PIL',
    'PIL.Image',
    'PIL.PngImagePlugin',
    'PIL.JpegImagePlugin',
    'PIL.GifImagePlugin',
    'PIL.BmpImagePlugin',
    'PIL.WebPImagePlugin',
    'gspread',
    'google.auth',
    'google.auth.transport.requests',
    'google.oauth2.service_account',
    'googleapiclient',
    'core',
    'core.models',
    'core.shift_manager',
    'core.local_cache',
    'core.google_sheets',
    'core.analytics',
    'config'
]

a = Analysis(
    ['server.py'],
    pathex=[BASE_DIR],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ShiftManagement',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(BASE_DIR, 'assets', 'logo.ico') if os.path.exists(os.path.join(BASE_DIR, 'assets', 'logo.ico')) else None
)
