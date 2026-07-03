"""Filler-word transcription via Google Cloud Speech-to-Text.

The synchronous ``SpeechClient.recognize`` call is capped at roughly one
minute of audio per request, so a full clip's audio is sliced into
``google_chunk_seconds``-long chunks first, transcribed one at a time, and
the per-chunk word timestamps are shifted back into the clip's own
timeline before being handed to ``filler_words.find_filler_intervals``.

Requires:
    pip install google-cloud-speech
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
(standard Application Default Credentials lookup -- see README.md)

Chunk boundaries are not overlapped, so a filler word that straddles a
chunk boundary can be missed. Fine for an MVP; tighten later if it turns
out to matter in practice.
"""

import os
from typing import List

from davinci_auto_cut.audio_extract import extract_audio_segment
from davinci_auto_cut.filler_words import WordTiming


def transcribe_words(
    wav_path: str,
    total_duration: float,
    language_code: str = "ja-JP",
    chunk_seconds: float = 55.0,
    temp_dir: str = None,
) -> List[WordTiming]:
    try:
        from google.cloud import speech
    except ImportError as exc:
        raise ImportError(
            "Filler-word removal requires the 'google-cloud-speech' package. "
            "Install it with: pip install google-cloud-speech"
        ) from exc

    client = speech.SpeechClient()
    words: List[WordTiming] = []

    offset = 0.0
    while offset < total_duration:
        dur = min(chunk_seconds, total_duration - offset)
        chunk_path = extract_audio_segment(
            wav_path, offset, dur, sample_rate=16000, temp_dir=temp_dir
        )
        try:
            with open(chunk_path, "rb") as f:
                content = f.read()

            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=language_code,
                enable_word_time_offsets=True,
                enable_automatic_punctuation=True,
            )
            response = client.recognize(config=config, audio=audio)

            for result in response.results:
                if not result.alternatives:
                    continue
                for word_info in result.alternatives[0].words:
                    words.append(
                        WordTiming(
                            word=word_info.word,
                            start=word_info.start_time.total_seconds() + offset,
                            end=word_info.end_time.total_seconds() + offset,
                        )
                    )
        finally:
            os.remove(chunk_path)

        offset += dur

    return words
