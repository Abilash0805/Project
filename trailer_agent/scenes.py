"""Scene-cut detection using ffmpeg's scene-score select filter."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ffmpeg import run_ffmpeg

# metadata=print emits pairs of lines on stdout:
#   frame:12   pts:98304   pts_time:4.096
#   lavfi.scene_score=0.412
_FRAME_RE = re.compile(r"pts_time:(?P<t>[0-9.]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=(?P<s>[0-9.]+)")


@dataclass
class Cut:
    time: float
    score: float


@dataclass
class Scene:
    """A contiguous run of footage between two detected cuts."""

    start: float
    end: float
    cut_score: float = 0.0    # how hard the cut into this scene was (visual change)
    energy: float = 0.0       # mean normalized loudness, filled in by analysis
    peak: float = 0.0         # peak normalized loudness
    motion: float = 0.0       # mean normalized visual motion (frame difference)
    has_speech: bool = False  # overlaps a detected speech region
    text: str = ""            # transcript overlapping this scene

    @property
    def excitement(self) -> float:
        """Composite score a trailer editor would call 'intensity'."""
        return 0.5 * self.energy + 0.35 * self.motion + 0.15 * self.peak

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_scene_output(output: str) -> list[Cut]:
    """Parse ffmpeg metadata=print output into cut timestamps."""
    cuts: list[Cut] = []
    pending_time: float | None = None
    for line in output.splitlines():
        m = _FRAME_RE.search(line)
        if m:
            pending_time = float(m.group("t"))
            continue
        m = _SCORE_RE.search(line)
        if m and pending_time is not None:
            cuts.append(Cut(time=pending_time, score=float(m.group("s"))))
            pending_time = None
    return cuts


def detect_cuts(path: str, threshold: float = 0.27) -> list[Cut]:
    output = run_ffmpeg(
        [
            "-i", path,
            "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
            "-an", "-sn",
            "-f", "null", "-",
        ],
        capture=True,
        timeout=1800,
    )
    return parse_scene_output(output)


def build_scenes(
    cuts: list[Cut],
    duration: float,
    *,
    min_len: float = 1.2,
    max_len: float = 25.0,
) -> list[Scene]:
    """Turn cut points into scenes; merge slivers, split marathons."""
    boundaries: list[tuple[float, float]] = [(0.0, 0.0)]
    for cut in sorted(cuts, key=lambda c: c.time):
        if 0.0 < cut.time < duration:
            boundaries.append((cut.time, cut.score))
    scenes: list[Scene] = []
    for i, (start, score) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else duration
        if end - start <= 0:
            continue
        scenes.append(Scene(start=start, end=end, cut_score=score))

    # merge scenes shorter than min_len into the previous scene
    merged: list[Scene] = []
    for scene in scenes:
        if merged and scene.duration < min_len:
            merged[-1].end = scene.end
        elif not merged and scene.duration < min_len and len(scenes) > 1:
            scene_next = scene  # keep, will absorb next iteration via normal flow
            merged.append(scene_next)
        else:
            merged.append(scene)

    # split scenes longer than max_len into equal chunks
    final: list[Scene] = []
    for scene in merged:
        if scene.duration <= max_len:
            final.append(scene)
            continue
        n = int(scene.duration // max_len) + 1
        step = scene.duration / n
        for k in range(n):
            final.append(
                Scene(
                    start=scene.start + k * step,
                    end=scene.start + (k + 1) * step,
                    cut_score=scene.cut_score if k == 0 else 0.0,
                )
            )
    return final
