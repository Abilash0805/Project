"""Optional speech-to-text via faster-whisper. Degrades gracefully when absent."""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class SpeechSegment:
    start: float
    end: float
    text: str


def transcribe(path: str, *, model_size: str = "base") -> list[SpeechSegment] | None:
    """Return speech segments, or None when faster-whisper isn't installed."""
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError:
        log.info("faster-whisper not installed; skipping transcription "
                 "(pip install 'trailer-agent[transcribe]' to enable)")
        return None

    try:
        model = WhisperModel(model_size, compute_type="int8")
        segments, _info = model.transcribe(path, vad_filter=True)
        return [
            SpeechSegment(start=s.start, end=s.end, text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]
    except Exception as exc:  # transcription is best-effort; never fail the pipeline
        log.warning("Transcription failed (%s); continuing without it", exc)
        return None
