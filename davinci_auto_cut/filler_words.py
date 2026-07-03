"""Match a transcript's words against a filler-word lexicon.

Pure logic, no external dependencies -- unit-testable in any environment.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Sequence, Tuple

_PUNCT_RE = re.compile(r"[.,!?、。！？…\-‐-―]")


@dataclass
class WordTiming:
    word: str
    start: float  # seconds
    end: float


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _PUNCT_RE.sub("", text)
    return text.strip().lower()


def _phrase_tokens(filler_words: Sequence[str]) -> List[Tuple[str, ...]]:
    """Turn each filler entry into a tuple of normalized tokens, e.g.
    "you know" -> ("you", "know"). Sorted longest-phrase-first so greedy
    matching prefers multi-word fillers over a prefix single-word one.
    """

    phrases = [tuple(normalize(w).split()) for w in filler_words]
    phrases = [p for p in phrases if p]
    phrases.sort(key=len, reverse=True)
    return phrases


def find_filler_intervals(
    words: List[WordTiming],
    filler_words: Sequence[str],
) -> List[Tuple[float, float]]:
    """Return ``(start, end)`` second-intervals covering every run of
    consecutive words that matches an entry in ``filler_words``.
    """

    phrases = _phrase_tokens(filler_words)
    normalized = [normalize(w.word) for w in words]

    intervals: List[Tuple[float, float]] = []
    i = 0
    n = len(words)
    while i < n:
        matched_len = 0
        for phrase in phrases:
            plen = len(phrase)
            if i + plen <= n and tuple(normalized[i : i + plen]) == phrase:
                matched_len = plen
                break
        if matched_len:
            intervals.append((words[i].start, words[i + matched_len - 1].end))
            i += matched_len
        else:
            i += 1

    return intervals
