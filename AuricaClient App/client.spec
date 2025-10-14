# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = []
for mod in ('webview', 'pyautogui'):
    hiddenimports += collect_submodules(mod)

# WICHTIG: alle PyObjC-Bridges + UTI reintun
for mod in (
    'objc',
    'Foundation', 'pyobjc_framework_Foundation',
    'AppKit', 'pyobjc_framework_AppKit',
    'WebKit', 'pyobjc_framework_WebKit',
    'CoreFoundation', 'pyobjc_framework_CoreFoundation',
    'UniformTypeIdentifiers', 'pyobjc_framework_UniformTypeIdentifiers',
):
    hiddenimports += collect_submodules(mod)

if sys.platform == 'win32':
    hiddenimports += collect_submodules('win32com')
    hiddenimports += ['win32timezone']

# Optional: minimaler Laufzeithook, der UTI garantiert importiert
# Lege eine Datei runtime_hook_uti.py neben der spec ab mit:
#   import UniformTypeIdentifiers  # noqa: F401
runtime_hooks = ['runtime_hook_uti.py']

a = Analysis(
    ['client_app.py'],
    pathex=['.'],
    datas=[],
    hiddenimports=hiddenimports,
    binaries=[],
    hookspath=[],
    runtime_hooks=runtime_hooks,
    excludes=[],
    noarchive=False
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='AuricaClient',
    console=False,     # bei Bedarf True zum Debuggen
    debug=False,
    strip=False,
    upx=False,
)

app = BUNDLE(
    exe,
    name='AuricaClient.app',
    info_plist={
        'NSMicrophoneUsageDescription': 'Aurica benötigt Mikrofonzugriff für Live-Transkript.',
        'NSAppleEventsUsageDescription': 'Aurica steuert andere Apps (Apple Events), um Text einzufügen.',
        # optional sinnvoll auf macOS (sonst fragt OpenPanel evtl. öfter):
        # 'NSDocumentsFolderUsageDescription': 'Dateien aus Dokumente öffnen.',
        # 'NSDownloadsFolderUsageDescription': 'Dateien aus Downloads öffnen.',
    }
)
