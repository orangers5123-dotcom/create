"""Resolve the ffmpeg/ffprobe binaries robustly.

A GUI app launched by double-clicking in Finder (or via `open`) does not
inherit the shell's PATH from .zshrc/.bash_profile, so a Homebrew-installed
ffmpeg that works fine from Terminal can be invisible to the app (PATH is
just the bare macOS default). Check a handful of common install locations
in addition to PATH before giving up.
"""

import os
import shutil

_COMMON_DIRS = [
    "/opt/homebrew/bin",  # Homebrew on Apple Silicon
    "/usr/local/bin",  # Homebrew on Intel Mac
    "/opt/local/bin",  # MacPorts
]


class BinaryNotFoundError(RuntimeError):
    pass


def locate(name: str) -> str:
    """Return the full path to the ``name`` binary (e.g. "ffmpeg"), checking
    PATH first and then a few common install locations.
    """

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
