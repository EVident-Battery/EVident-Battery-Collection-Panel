# -*- mode: python ; coding: utf-8 -*-
import subprocess

# Stamp the commit being built into a gitignored _version.py that the exe
# bundles; version.get_version() reads it at runtime
_commit = subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
).stdout.strip() or "unknown"
with open("_version.py", "w") as _f:
    _f.write(f'COMMIT = "{_commit}"
')


a = Analysis(
    ['auto_collector.py'],
    pathex=[],
    binaries=[],
    datas=[('media', 'media')],
    hiddenimports=['_version'],
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
    name='AdvancedDeviceHub',
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
app = BUNDLE(
    exe,
    name='AdvancedDeviceHub.app',
    icon=None,
    bundle_identifier=None,
)
