"""Application version derived from the git commit being run/built.

Packaged builds: the .spec writes a gitignored _version.py at build time
containing the short hash of the commit being built (no chicken-and-egg -
the generated file is never committed, so it doesn't change the hash).
Running from source: ask git directly; a trailing * means uncommitted
changes were present.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def get_version() -> str:
    try:
        from _version import COMMIT  # generated at build time by the .spec
        return COMMIT
    except ImportError:
        pass

    try:
        root = Path(__file__).resolve().parent
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=root, timeout=3,
        )
        if r.returncode == 0 and r.stdout.strip():
            commit = r.stdout.strip()
            # Tracked modifications only: untracked files (logs, local
            # tools) shouldn't brand the build as dirty
            dirty = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                capture_output=True, text=True, cwd=root, timeout=3,
            )
            if dirty.returncode == 0 and dirty.stdout.strip():
                commit += "*"
            return commit
    except Exception:
        pass

    return "dev"
