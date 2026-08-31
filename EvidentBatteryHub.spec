# -*- mode: python ; coding: utf-8 -*-
import os

# macOS code signing: set EVB_CODESIGN_IDENTITY to e.g.
#   "Developer ID Application: EVident Battery Inc (TEAMID)"
# to produce a hardened-runtime, notarizable build (see build-mac.sh).
# Unset -> ad-hoc signed, unchanged behavior on Windows/Linux.
_SIGN_ID = os.environ.get("EVB_CODESIGN_IDENTITY") or None

a = Analysis(
    ['auto_collector.py'],
    pathex=[],
    binaries=[],
    datas=[('media', 'media')],
    hiddenimports=[],
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
    name='EvidentBatteryHub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=_SIGN_ID,
    entitlements_file='entitlements.plist' if _SIGN_ID else None,
    icon=['media/favicon_white.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EvidentBatteryHub',
)
app = BUNDLE(
    coll,
    name='EvidentBatteryHub.app',
    icon='media/favicon_white.icns',
    bundle_identifier='com.evidentbattery.devicehub',
    info_plist={
        'LSMinimumSystemVersion': '14.0',
        'NSLocalNetworkUsageDescription':
            'EVident Battery Device Hub discovers EVB sensors on your local network.',
        'NSBonjourServices': ['_evbs._tcp'],
        'NSHighResolutionCapable': True,
    },
)
