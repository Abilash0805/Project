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
        # Force CPU: the default auto-detect tries to load CUDA/cuBLAS
        # (cublas64_*.dll), which fails on the many machines without an NVIDIA
        # GPU toolkit. int8 on CPU is plenty fast for the base model, and keeps
        # the dialogue features working fully offline everywhere.
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        # No word_timestamps: it runs a slow extra alignment pass per segment
        # (the cause of multi-minute stalls on CPU) and we only use segment-level
        # timing. VAD trims silence so we don't transcribe dead air.
        segments, info = model.transcribe(path, vad_filter=True)
        log.info("Transcribing %s speech (lang=%s)... this can take a few minutes "
                 "on CPU; pass --no-transcript to skip.",
                 "detected" if info else "", getattr(info, "language", "?"))
        out: list[SpeechSegment] = []
        for s in segments:  # generator — work happens as we iterate
            text = s.text.strip()
            if text:
                out.append(SpeechSegment(start=s.start, end=s.end, text=text))
            if len(out) % 25 == 0 and out:
                log.info("  ...transcribed %d lines (%.0fs in)", len(out), s.end)
        log.info("Transcription done: %d lines", len(out))
        return out
    except Exception as exc:  # transcription is best-effort; never fail the pipeline
        log.warning("Transcription failed (%s); continuing without it", exc)
        return None
