"""Resolve the ffmpeg/ffprobe binaries robustly.

A GUI app launched by double-clicking in Finder (or via `open`) does not
inherit the shell's PATH from .zshrc/.bash_profile, so a Homebrew-installed
ffmpeg that works fine from Terminal can be invisible to the app (PATH is
just the bare macOS default). Rather than depend on PATH visibility at all,
a packaged .app bundles its own copy of ffmpeg/ffprobe (see
``bundle_ffmpeg.sh`` at the repo root) under ``ffmpeg_bin/`` alongside the
frozen app's other data files -- that bundled copy is checked first. PATH
and a handful of common install locations remain as a fallback for running
from source (``python3 -m ...``), where there's no bundle to check.
"""

import os
import shutil
import sys

_COMMON_DIRS = [
    "/opt/homebrew/bin",  # Homebrew on Apple Silicon
    "/usr/local/bin",  # Homebrew on Intel Mac
    "/opt/local/bin",  # MacPorts
]

# The name PyInstaller's --add-binary destination uses; bundle_ffmpeg.sh and
# the packaging docs must agree with this.
BUNDLED_SUBDIR = "ffmpeg_bin"


class BinaryNotFoundError(RuntimeError):
    pass


def _bundled_dir():
    """The directory a frozen (PyInstaller) build's bundled binaries live
    in, or ``None`` when running from source -- there's nothing bundled to
    check in that case.
    """

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return os.path.join(meipass, BUNDLED_SUBDIR)
    return None


def locate(name: str) -> str:
    """Return the full path to the ``name`` binary (e.g. "ffmpeg").

    Checks, in order: the packaged app's own bundled copy (if running
    frozen and it was included at build time), PATH, then a few common
    install locations.
    """

    bundled_dir = _bundled_dir()
    if bundled_dir:
        candidate = os.path.join(bundled_dir, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    found = shutil.which(name)
    if found:
        return found

    for directory in _COMMON_DIRS:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    raise BinaryNotFoundError(
        f"'{name}' が見つかりません。`brew install ffmpeg` でインストールしてください。"
        f"（インストール済みの場合、GUIアプリからは通常のPATHが見えないことがあります。"
        f"確認済みの場所: {', '.join(_COMMON_DIRS)}）"
    )
