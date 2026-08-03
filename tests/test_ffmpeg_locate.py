import pytest

from davinci_auto_cut.ffmpeg_locate import BinaryNotFoundError, locate


def test_locate_prefers_path(monkeypatch):
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
