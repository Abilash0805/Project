"""Single-decode video analysis: scene cuts, motion, and visual fingerprints.

One ffmpeg pass over a downscaled stream produces:
  - scene-change cut points (select scene-score)
  - a motion curve (signalstats YDIF: mean luma difference between frames)
  - 8x8 grayscale fingerprints at 1 fps, for visual-similarity dedupe
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from .audio import EnergyCurve, EnergyPoint
from .ffmpeg import run_ffmpeg
from .scenes import Cut, parse_scene_output

SIG_SIZE = 8  # fingerprints are SIG_SIZE x SIG_SIZE grayscale
SIG_BYTES = SIG_SIZE * SIG_SIZE
MOTION_FPS = 5

import re

_FRAME_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)")
_YDIF_RE = re.compile(r"lavfi\.signalstats\.YDIF=(?P<v>[0-9.]+)")


def parse_motion_output(output: str) -> list[EnergyPoint]:
    points: list[EnergyPoint] = []
    pending_time: float | None = None
    for line in output.splitlines():
        m = _FRAME_RE.search(line)
        if m:
            pending_time = float(m.group("t"))
            continue
        m = _YDIF_RE.search(line)
        if m and pending_time is not None:
            points.append(EnergyPoint(time=pending_time, rms_db=float(m.group("v"))))
            pending_time = None
    return points


class Fingerprints:
    """1 fps 8x8 grayscale frames; frame i covers second [i, i+1)."""

    def __init__(self, raw: bytes):
        self._frames = [
            raw[i : i + SIG_BYTES] for i in range(0, len(raw) - SIG_BYTES + 1, SIG_BYTES)
        ]

    def __len__(self) -> int:
        return len(self._frames)

    def at(self, t: float) -> bytes | None:
        i = int(t)
        if 0 <= i < len(self._frames):
            return self._frames[i]
        return self._frames[-1] if self._frames else None

    @staticmethod
    def distance(a: bytes | None, b: bytes | None) -> float:
        """Mean absolute pixel difference, 0-255. ~<25 means visually similar."""
        if not a or not b or len(a) != len(b):
            return 255.0
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


@dataclass
class VideoStats:
    cuts: list[Cut]
    motion: EnergyCurve
    fingerprints: Fingerprints


def analyze_video(path: str, *, scene_threshold: float = 0.27) -> VideoStats:
    workdir = tempfile.mkdtemp(prefix="trailer_vstats_")
    cuts_file = os.path.join(workdir, "cuts.txt")
    motion_file = os.path.join(workdir, "motion.txt")
    sigs_file = os.path.join(workdir, "sigs.gray")
    try:
        run_ffmpeg(
            [
                "-i", path,
                "-filter_complex",
                (
                    "[0:v]scale=320:-2:flags=fast_bilinear,split=3[sc][mo][sg];"
                    f"[sc]select='gt(scene,{scene_threshold})',"
                    f"metadata=print:file={cuts_file}[v1];"
                    f"[mo]fps={MOTION_FPS},signalstats,"
                    f"metadata=print:key=lavfi.signalstats.YDIF:file={motion_file}[v2];"
                    f"[sg]fps=1,scale={SIG_SIZE}:{SIG_SIZE},format=gray[v3]"
                ),
                "-map", "[v1]", "-f", "null", os.devnull,
                "-map", "[v2]", "-f", "null", os.devnull,
                "-map", "[v3]", "-f", "rawvideo", sigs_file,
            ],
            timeout=3600,
        )
        with open(cuts_file) as f:
            cuts = parse_scene_output(f.read())
        with open(motion_file) as f:
            motion = EnergyCurve(parse_motion_output(f.read()))
        with open(sigs_file, "rb") as f:
            fingerprints = Fingerprints(f.read())
        return VideoStats(cuts=cuts, motion=motion, fingerprints=fingerprints)
    finally:
        for p in (cuts_file, motion_file, sigs_file):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(workdir)
        except OSError:
            pass
