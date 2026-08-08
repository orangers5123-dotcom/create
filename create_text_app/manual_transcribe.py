"""Transcribe one short mic-recorded WAV clip into plain text, for manual
dictation mode. Unlike the auto-transcribe flow this doesn't need
timestamps back -- the user already set the segment's start/end on the
timeline, they're just dictating what to put in it.
"""

from create_text_app.whisper_model import get_model

LANGUAGE_AUTO = "auto"


def transcribe_clip(wav_path: str, model_size: str, language: str = LANGUAGE_AUTO) -> str:
    """Return the recognized text for ``wav_path``. VAD is left off --
    these are short, user-bounded recordings (start/stop button), so there's
    no need to hunt for speech inside a longer file, and VAD can otherwise
    clip quiet speech near the edges.
    """

    model = get_model(model_size)

    transcribe_kwargs = {}
    if language != LANGUAGE_AUTO:
        transcribe_kwargs["language"] = language

    raw_segments, _info = model.transcribe(wav_path, vad_filter=False, **transcribe_kwargs)
    text = " ".join(seg.text.strip() for seg in raw_segments if seg.text.strip())
    return text
