# -*- mode: python ; coding: utf-8 -*-
import sys

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('config', 'config'), ('src', 'src'), ('.env.example', '.')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 
                   'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
                   'uvicorn.lifespan', 'uvicorn.lifespan.on',
                   'tiktoken_ext', 'tiktoken_ext.openai_public'],
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
    a.binaries,
    a.datas,
    [],
    name='Stet',
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

# macOS app bundle - creates a proper .app that hides console completely
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Stet.app',
        icon=None,  # Add icon path here if you have one: 'icon.icns'
        bundle_identifier='com.stet.app',
        info_plist={
            'CFBundleName': 'Stet',
            'CFBundleDisplayName': 'Stet',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
            'LSBackgroundOnly': False,
        },
    )
