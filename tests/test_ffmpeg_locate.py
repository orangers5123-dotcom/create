import sys

import pytest

from davinci_auto_cut.ffmpeg_locate import BinaryNotFoundError, locate


def _make_binary(directory, name="ffmpeg"):
    directory.mkdir(exist_ok=True)
    binary = directory / name
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    return binary


def test_locate_prefers_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert locate("ffmpeg") == "/usr/bin/ffmpeg"


def test_locate_prefers_bundled_binary_when_frozen(monkeypatch, tmp_path):
    bundled_dir = tmp_path / "ffmpeg_bin"
    bundled_binary = _make_binary(bundled_dir)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    # Even if PATH also has one, the bundled copy wins -- it's guaranteed to
    # be there regardless of what the launching environment's PATH looks like.
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    assert locate("ffmpeg") == str(bundled_binary)


def test_locate_falls_back_to_path_when_not_frozen(monkeypatch, tmp_path):
    # A bundled-looking dir existing on disk shouldn't matter when we're not
    # actually running as a frozen (PyInstaller) build.
    bundled_dir = tmp_path / "ffmpeg_bin"
    _make_binary(bundled_dir)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    assert locate("ffmpeg") == "/usr/bin/ffmpeg"


def test_locate_falls_back_to_path_when_frozen_but_binary_not_bundled(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)  # no ffmpeg_bin/ underneath
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")

    assert locate("ffmpeg") == "/usr/bin/ffmpeg"


def test_locate_falls_back_to_common_homebrew_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)

    fake_dir = tmp_path / "homebrew_bin"
    fake_dir.mkdir()
    fake_binary = fake_dir / "ffmpeg"
    fake_binary.write_text("#!/bin/sh\n")
    fake_binary.chmod(0o755)

    monkeypatch.setattr("davinci_auto_cut.ffmpeg_locate._COMMON_DIRS", [str(fake_dir)])
    assert locate("ffmpeg") == str(fake_binary)


def test_locate_raises_clear_error_when_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("davinci_auto_cut.ffmpeg_locate._COMMON_DIRS", [str(tmp_path)])

    with pytest.raises(BinaryNotFoundError, match="ffmpeg"):
        locate("ffmpeg")
