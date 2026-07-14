"""Audio analysis: per-window loudness (excitement) + silence/speech detection.

Both signals come out of a single ffmpeg decode pass: RMS windows are printed
to stdout via ametadata, silencedetect logs land on stderr.
"""

from __future__ import annotations

import re
import subprocess
from bisect import bisect_right
from dataclasses import dataclass

from .ffmpeg import FFmpegError, _find

_FRAME_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)")
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(?P<db>-?[0-9.]+|-inf|inf|nan)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(?P<t>-?[0-9.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(?P<t>[0-9.]+)")

SILENCE_DB = -70.0  # anything at/below this is treated as silence


@dataclass
class EnergyPoint:
    time: float
    rms_db: float


@dataclass
class SpeechRegion:
    start: float
    end: float


class EnergyCurve:
    """Normalized signal over time, sampled in fixed windows (works for any metric)."""

    def __init__(self, points: list[EnergyPoint]):
        self.points = sorted(points, key=lambda p: p.time)
        self._times = [p.time for p in self.points]
        dbs = [max(p.rms_db, SILENCE_DB) for p in self.points]
        if dbs:
            lo, hi = min(dbs), max(dbs)
            span = (hi - lo) or 1.0
            self._norm = [(db - lo) / span for db in dbs]
        else:
            self._norm = []

    @property
    def times(self) -> list[float]:
        return self._times

    @property
    def values(self) -> list[float]:
        return self._norm

    def window(self, start: float, end: float) -> list[float]:
        i = bisect_right(self._times, start)
        j = bisect_right(self._times, end)
        # include the sample whose window contains `start`
        i = max(i - 1, 0)
        return self._norm[i:j] or ([self._norm[min(i, len(self._norm) - 1)]] if self._norm else [])

    def mean(self, start: float, end: float) -> float:
        values = self.window(start, end)
        return sum(values) / len(values) if values else 0.0

    def peak(self, start: float, end: float) -> float:
        values = self.window(start, end)
        return max(values) if values else 0.0


def parse_astats_output(output: str) -> list[EnergyPoint]:
    points: list[EnergyPoint] = []
    pending_time: float | None = None
    for line in output.splitlines():
        m = _FRAME_RE.search(line)
        if m:
            pending_time = float(m.group("t"))
            continue
        m = _RMS_RE.search(line)
        if m and pending_time is not None:
            raw = m.group("db")
            db = SILENCE_DB if raw in ("-inf", "inf", "nan") else float(raw)
            points.append(EnergyPoint(time=pending_time, rms_db=db))
            pending_time = None
    return points


def parse_silence_output(output: str, duration: float) -> list[SpeechRegion]:
    """Invert silencedetect's silence intervals into speech/sound regions."""
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in output.splitlines():
        m = _SILENCE_START_RE.search(line)
        if m:
            start = max(float(m.group("t")), 0.0)
            continue
        m = _SILENCE_END_RE.search(line)
        if m and start is not None:
            silences.append((start, float(m.group("t"))))
            start = None
    if start is not None:  # silence runs to the end of the file
        silences.append((start, duration))

    regions: list[SpeechRegion] = []
    cursor = 0.0
    for s_start, s_end in sorted(silences):
        if s_start - cursor > 0.15:
            regions.append(SpeechRegion(start=cursor, end=s_start))
        cursor = max(cursor, s_end)
    if duration - cursor > 0.15:
        regions.append(SpeechRegion(start=cursor, end=duration))
    return regions


@dataclass
class AudioAnalysis:
    energy: EnergyCurve
    speech: list[SpeechRegion]


def analyze_audio(
    path: str,
    duration: float,
    *,
    window_seconds: float = 0.5,
    silence_db: float = -32.0,
    min_silence: float = 0.35,
) -> AudioAnalysis:
    """One decode pass: RMS windows on stdout, silencedetect log on stderr."""
    n_samples = max(int(48000 * window_seconds), 1024)
    cmd = [
        _find("ffmpeg"), "-hide_banner", "-y",
        "-i", path,
        "-map", "0:a:0",
        "-af",
        (
            f"aresample=48000,silencedetect=noise={silence_db}dB:d={min_silence},"
            f"asetnsamples=n={n_samples},"
            "astats=metadata=1:reset=1,"
            "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
        ),
        "-f", "null", "-",
    ]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1800
    )
    if proc.returncode != 0:
        raise FFmpegError(f"audio analysis failed ({proc.returncode}):\n{proc.stderr[-4000:]}")
    return AudioAnalysis(
        energy=EnergyCurve(parse_astats_output(proc.stdout)),
        speech=parse_silence_output(proc.stderr, duration),
    )


def snap_to_speech(
    start: float, end: float, speech: list[SpeechRegion], *, tolerance: float = 1.2
) -> tuple[float, float]:
    """Nudge a cut window so it doesn't clip a spoken phrase mid-word.

    If a boundary falls inside a speech region and the region's edge is within
    tolerance, move the boundary to that edge (expanding to include the phrase
    start, or pulling in to release before the phrase ends).
    """
    new_start, new_end = start, end
    for region in speech:
        if region.start < new_start < region.end:
            if new_start - region.start <= tolerance:
                new_start = region.start          # include the start of the phrase
            elif region.end - new_start <= tolerance:
                new_start = region.end            # skip the tail of the phrase
        if region.start < new_end < region.end:
            if region.end - new_end <= tolerance:
                new_end = region.end              # let the phrase finish
            elif new_end - region.start <= tolerance:
                new_end = region.start            # cut before the phrase starts
    if new_end - new_start < 0.5:                 # never collapse the shot
        return start, end
    return new_start, new_end
