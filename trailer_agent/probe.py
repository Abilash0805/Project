"""Media metadata via ffprobe."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction

from .ffmpeg import FFmpegError, run_ffprobe


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def probe(path: str) -> MediaInfo:
    raw = run_ffprobe(
        [
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            path,
        ]
    )
    data = json.loads(raw)

    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise FFmpegError(f"No video stream found in {path}")
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0.0)
    if duration <= 0:
        raise FFmpegError(f"Could not determine duration of {path}")

    fps = 30.0
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    try:
        frac = Fraction(rate)
        if frac > 0:
            fps = float(frac)
    except (ValueError, ZeroDivisionError):
        pass

    return MediaInfo(
        path=path,
        duration=duration,
        width=int(video.get("width", 1920)),
        height=int(video.get("height", 1080)),
        fps=fps,
        has_audio=audio is not None,
    )
