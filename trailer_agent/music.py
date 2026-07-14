"""Music beat detection so cuts can land on the beat.

Pure-Python onset-flux autocorrelation over an ffmpeg loudness envelope:
  1. sample the track's RMS at 50 ms hops
  2. onset strength = positive energy flux
  3. tempo = best autocorrelation lag in the 60-180 BPM range
     (with octave-error correction by also rewarding the doubled lag)
  4. phase = grid offset that captures the most onset strength
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

HOP = 0.05           # envelope hop in seconds
BPM_MIN, BPM_MAX = 60.0, 180.0
MIN_CONFIDENCE = 1.35  # best lag must beat the average this much to trust the grid


@dataclass
class BeatGrid:
    bpm: float
    interval: float      # seconds per beat
    first_beat: float    # offset of the first beat in the track

    def quantize(self, seconds: float, *, min_beats: int = 1) -> float:
        """Round a duration to the nearest whole number of beats."""
        beats = max(round(seconds / self.interval), min_beats)
        return beats * self.interval


def onset_envelope(values: list[float]) -> list[float]:
    """Positive flux of a normalized energy series."""
    flux = [0.0]
    for prev, cur in zip(values, values[1:]):
        flux.append(max(cur - prev, 0.0))
    return flux


def detect_grid(times: list[float], values: list[float]) -> BeatGrid | None:
    """Estimate a beat grid from an energy envelope. None when not confidently rhythmic."""
    if len(values) < 64:
        return None
    hop = HOP
    if len(times) > 1:
        deltas = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
        if deltas:
            hop = deltas[len(deltas) // 2]

    onset = onset_envelope(values)
    n = len(onset)
    lag_min = max(int((60.0 / BPM_MAX) / hop), 2)
    lag_max = min(int((60.0 / BPM_MIN) / hop), n // 2)
    if lag_max <= lag_min:
        return None

    def autocorr(lag: int) -> float:
        total = sum(onset[i] * onset[i + lag] for i in range(n - lag))
        return total / (n - lag)

    scores: dict[int, float] = {}
    for lag in range(lag_min, lag_max + 1):
        score = autocorr(lag)
        if 2 * lag < n:  # reward the doubled lag to fight octave errors
            score += 0.5 * autocorr(2 * lag)
        scores[lag] = score

    best_lag = max(scores, key=scores.get)  # type: ignore[arg-type]
    mean_score = sum(scores.values()) / len(scores)
    if mean_score <= 0 or scores[best_lag] / mean_score < MIN_CONFIDENCE:
        log.info("Music is not confidently rhythmic; skipping beat sync")
        return None

    # phase: which offset along the grid catches the most onset strength
    best_offset, best_sum = 0, -1.0
    for offset in range(best_lag):
        s = sum(onset[i] for i in range(offset, n, best_lag))
        if s > best_sum:
            best_offset, best_sum = offset, s

    interval = best_lag * hop
    grid = BeatGrid(bpm=60.0 / interval, interval=interval, first_beat=best_offset * hop)
    log.info("Detected music tempo: %.1f BPM (beat every %.3fs, first beat at %.2fs)",
             grid.bpm, grid.interval, grid.first_beat)
    return grid


def analyze_music(path: str) -> BeatGrid | None:
    """Detect the beat grid of a music file. Returns None on any failure."""
    try:
        from .audio import analyze_audio

        duration = probe_audio_duration(path)
        analysis = analyze_audio(path, duration, window_seconds=HOP)
        return detect_grid(analysis.energy.times, analysis.energy.values)
    except Exception as exc:
        log.warning("Music analysis failed (%s); cutting without beat sync", exc)
        return None


def probe_audio_duration(path: str) -> float:
    import json

    from .ffmpeg import run_ffprobe

    raw = run_ffprobe(
        ["-v", "error", "-print_format", "json", "-show_format", path]
    )
    return float(json.loads(raw).get("format", {}).get("duration") or 0.0)
