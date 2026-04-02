# Linux / Raspberry Pi Setup Guide

This document covers how to get the EVident Battery Collection Panel fully working on a Raspberry Pi (aarch64 / ARM64) running Debian Bookworm. It includes all the gotchas encountered along the way.

Tested on:
- Raspberry Pi 5 (aarch64)
- Debian GNU/Linux 12 (Bookworm)
- Python 3.11.2

---

## 1. System-Level Dependencies

### PyQt5

On ARM64 Linux, **PyQt5 cannot be installed via pip**. The `pip install PyQt5` command attempts to build from source, which fails because it requires `qmake` and the full Qt5 build toolchain. Instead, use the system package:

```bash
sudo apt install python3-pyqt5 python3-pyqt5.qtsvg
```

The `python3-pyqt5.qtsvg` package is required separately -- the base `python3-pyqt5` package does not include SVG support, and the app imports `PyQt5.QtSvg`.

**Why this happens:** PyQt5 publishes pre-built wheels for x86_64 (Windows, macOS, Linux), but not for ARM64. On ARM64 pip falls back to building from the source tarball, which requires Qt5 development headers and `qmake` -- a heavyweight dependency chain that's unnecessary when the distro already ships a working build.

### Emoji Rendering

Emoji characters (battery icon, clock, etc.) render as empty boxes by default on Raspberry Pi OS because no emoji font is installed. Fix:

```bash
sudo apt install fonts-noto-color-emoji
```

Restart the application after installing for the font to take effect.

---

## 2. Virtual Environment Setup

### The `--system-site-packages` Flag

The venv **must** be created with `--system-site-packages` so that it can access the system-installed PyQt5:

```bash
python3 -m venv --system-site-packages venv
```

If the venv was already created without this flag, you need to recreate it:

```bash
rm -rf venv
python3 -m venv --system-site-packages venv
```

**Why this matters:** By default, `python3 -m venv` creates an isolated environment that cannot see packages installed via `apt` (like `python3-pyqt5`). The `--system-site-packages` flag allows the venv to fall through to the system's `site-packages` directory for packages that aren't installed in the venv itself. This gives us the best of both worlds: pip-installable packages live in the venv, while system-only packages like PyQt5 remain accessible.

### Activating the venv

```bash
source venv/bin/activate
```

Always verify the venv is active and pointing to the correct location:

```bash
which python
# Should output: /path/to/project/venv/bin/python
```

This catches cases where activation silently fails or another venv takes precedence.

---

## 3. Python Dependencies

With the venv activated, install the pip-installable requirements:

```bash
pip install -r requirements.txt
```

Note: `pip` will skip PyQt5 if it detects the system package satisfying the version requirement (due to `--system-site-packages`). If it tries to build PyQt5 from source and fails, that means the system package isn't visible -- revisit the venv setup in Section 2.

The key dependencies are:

| Package    | Notes |
|------------|-------|
| PyQt5      | Must come from system `apt`, not pip (on ARM64) |
| requests   | HTTP client -- installs fine via pip |
| zeroconf   | mDNS sensor discovery -- installs fine via pip |
| numpy      | Installs via pip (pre-built ARM64 wheels available) |
| scipy      | Installs via pip (pre-built ARM64 wheels available) |
| pandas     | Installs via pip |
| matplotlib | Installs via pip |

---

## 4. Running the Application

```bash
source venv/bin/activate
python auto_collector.py
```

---

## 5. Building a Standalone Executable

### Install PyInstaller

```bash
pip install pyinstaller
```

### Build Command (Linux)

```bash
pyinstaller --noconsole --onefile --name="AdvancedDeviceHub" --add-data "media:media" ./auto_collector.py
```

The executable will be output to `dist/AdvancedDeviceHub`.

### Key Differences from Windows Build

| Aspect | Windows | Linux |
|--------|---------|-------|
| `--add-data` separator | `;` (semicolon) | `:` (colon) |
| `--icon` | `.ico` file works | **Ignored** -- icons are only supported on Windows/macOS. Use a `.desktop` file instead. |
| Output | `.exe` | ELF binary (no extension) |

**Windows build command (for reference):**
```bash
pyinstaller --noconsole --onefile --name="AdvancedDeviceHub" --icon="media/favicon_white.ico" --add-data "media;media" ./auto_collector.py
```

### Running the Built Executable

```bash
./dist/AdvancedDeviceHub
```

---

## 6. Git Branch Note

When switching to a remote branch locally, use the branch name without `origin/`:

```bash
# Wrong -- git expects a local branch name, not a remote ref
git switch origin/feature/monitoring

# Correct -- git auto-creates a local branch tracking the remote
git switch feature/monitoring
```

---

## Quick Start (TL;DR)

```bash
# System deps
sudo apt install python3-pyqt5 python3-pyqt5.qtsvg fonts-noto-color-emoji

# Venv
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Python deps
pip install -r requirements.txt

# Run
python auto_collector.py

# Build (optional)
pip install pyinstaller
pyinstaller --noconsole --onefile --name="AdvancedDeviceHub" --add-data "media:media" ./auto_collector.py
./dist/AdvancedDeviceHub
```
