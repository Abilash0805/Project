"""Optional speech-to-text via faster-whisper. Degrades gracefully when absent."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class SpeechSegment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


def transcribe(path: str, *, model_size: str = "base") -> list[SpeechSegment] | None:
    """Return speech segments (with word timestamps), or None when
    faster-whisper isn't installed."""
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        log.info("faster-whisper not installed; skipping transcription "
                 "(pip install 'trailer-agent[transcribe]' to enable)")
        return None

    try:
        model = WhisperModel(model_size, compute_type="int8")
        segments, _info = model.transcribe(path, vad_filter=True, word_timestamps=True)
        return [
            SpeechSegment(
                start=s.start,
                end=s.end,
                text=s.text.strip(),
                words=[
                    Word(start=w.start, end=w.end, text=w.word.strip())
                    for w in (s.words or [])
                ],
            )
            for s in segments
            if s.text.strip()
        ]
    except Exception as exc:  # transcription is best-effort; never fail the pipeline
        log.warning("Transcription failed (%s); continuing without it", exc)
        return None
