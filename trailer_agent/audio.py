"""Per-window loudness analysis — the 'excitement' signal for scene scoring."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

from .ffmpeg import run_ffmpeg

_FRAME_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)")
_RMS_RE = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(?P<db>-?[0-9.]+|-inf|inf|nan)")

SILENCE_DB = -70.0  # anything at/below this is treated as silence


@dataclass
class EnergyPoint:
    time: float
    rms_db: float


class EnergyCurve:
    """Normalized loudness over time, sampled in fixed windows."""

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


def analyze_energy(path: str, *, window_seconds: float = 0.5) -> EnergyCurve:
    n_samples = max(int(48000 * window_seconds), 1024)
    output = run_ffmpeg(
        [
            "-i", path,
            "-map", "0:a:0",
            "-af",
            (
                f"aresample=48000,asetnsamples=n={n_samples},"
                "astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"
            ),
            "-f", "null", "-",
        ],
        capture=True,
        timeout=1800,
    )
    return EnergyCurve(parse_astats_output(output))
