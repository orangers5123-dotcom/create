"""Play back a WAV file's audio through the default output device, so a
manual-dictation segment's real audio can be listened to (see
mic_recorder.py for the matching capture side, and frame_extract.py for
the silent-frame preview -- this fills the "what does this bit actually
sound like" gap neither of those covers).

``play_wav`` returns as soon as playback starts (sounddevice streams it on
its own thread) -- it does not block until finished.
"""


class AudioPlaybackError(RuntimeError):
    pass


def play_wav(path: str) -> None:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioPlaybackError(
            "音声再生には 'sounddevice' パッケージが必要です。"
            " pip install sounddevice でインストールしてください。"
        ) from exc

    from scipy.io import wavfile

    try:
        samplerate, data = wavfile.read(path)
    except Exception as exc:  # noqa: BLE001
        raise AudioPlaybackError(f"音声ファイルの読み込みに失敗しました: {exc}") from exc

    try:
        sd.play(data, samplerate)
    except Exception as exc:  # noqa: BLE001
        raise AudioPlaybackError(f"音声の再生に失敗しました: {exc}") from exc


def stop() -> None:
    """Stop whatever ``play_wav`` might currently be playing. A no-op if
    sounddevice isn't installed or nothing is playing.
    """

    try:
        import sounddevice as sd
    except ImportError:
        return
    sd.stop()
