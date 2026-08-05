# -*- mode: python ; coding: utf-8 -*-
import subprocess
from datetime import date, timedelta

# Stamp the commit being built into a gitignored _version.py that the exe
# bundles; version.get_version() reads it at runtime
_commit = subprocess.run(
    ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
).stdout.strip() or "unknown"
with open("_version.py", "w") as _f:
    _f.write(f'COMMIT = "{_commit}"\n')

# Stamp the trial window into a gitignored _trial_stamp.py; trial.py reads
# it at runtime. Only this spec writes it, so the regular build stays
# unrestricted from the same branch.
TRIAL_DAYS = 30
_built = date.today()
with open("_trial_stamp.py", "w") as _f:
    _f.write(f'BUILT = "{_built.isoformat()}"\n')
    _f.write(f'EXPIRY = "{(_built + timedelta(days=TRIAL_DAYS)).isoformat()}"\n')


a = Analysis(
    ['auto_collector.py'],
    pathex=[],
    binaries=[],
    datas=[('media', 'media')],
    hiddenimports=['_version', '_trial_stamp'],
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
    name='AdvancedDeviceHubTrialVersion',
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
    icon=['media\\favicon_white.ico'],
)
