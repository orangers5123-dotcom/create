"""Start/stop microphone recording into a WAV file, for per-segment manual
dictation. Uses ``sounddevice`` (PortAudio) to capture, buffering chunks in
memory and writing them out as a WAV file on stop -- recordings are only a
few seconds long so this is not a concern.
"""

from typing import Optional


class MicRecorderError(RuntimeError):
    pass


class MicRecorder:
    def __init__(self, samplerate: int = 16000, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self._stream = None
        self._chunks = []
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return

        try:
            import sounddevice as sd
        except ImportError as exc:
            raise MicRecorderError(
                "音声入力には 'sounddevice' パッケージが必要です。"
                " pip install sounddevice でインストールしてください。"
            ) from exc

        self._chunks = []

        def _callback(indata, frames, time_info, status):  # noqa: ARG001 -- sounddevice callback signature
            self._chunks.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=self.samplerate, channels=self.channels, dtype="int16", callback=_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise MicRecorderError(f"マイクの起動に失敗しました: {exc}") from exc

        self._recording = True

    def stop(self, out_path: str) -> Optional[str]:
        """Stop recording and write the captured audio to ``out_path`` as a
        mono WAV file. Returns ``out_path``, or ``None`` if nothing was
        captured (e.g. stopped immediately after starting).
        """

        if not self._recording:
            return None

        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._chunks:
            return None

        import numpy as np
        from scipy.io import wavfile

        data = np.concatenate(self._chunks, axis=0)
        self._chunks = []
        wavfile.write(out_path, self.samplerate, data)
        return out_path

    def cancel(self) -> None:
        """Stop recording (if active) and discard whatever was captured."""

        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._chunks = []
