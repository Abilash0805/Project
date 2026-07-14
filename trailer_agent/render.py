"""Render a TrailerPlan into a finished mp4 with ffmpeg.

Strategy: every timeline item becomes a uniformly-encoded segment file
(same codec/size/fps/audio layout), segments are concatenated losslessly,
then a final pass adds music (side-chain ducked under the original audio),
loudness normalization, and an end fade.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile

from .config import TrailerOptions
from .ffmpeg import run_ffmpeg
from .probe import MediaInfo
from .storyboard import TimelineItem, TrailerPlan

log = logging.getLogger(__name__)

FPS = 30
CINEMASCOPE = 2.39

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]


def find_font() -> str | None:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def drawtext_escape(text: str) -> str:
    """Escape text for use inside a drawtext filter argument."""
    out = text.replace("\\", "\\\\")
    for ch in (":", "'", ",", "[", "]", ";", "="):
        out = out.replace(ch, "\\" + ch)
    return out


def atempo_chain(speed: float) -> str:
    """Build an atempo filter chain; each stage must stay within [0.5, 2.0]."""
    stages: list[float] = []
    remaining = speed
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    stages.append(remaining)
    return ",".join(f"atempo={s:.6g}" for s in stages)


def _frame_size(opts: TrailerOptions) -> tuple[int, int]:
    height = opts.output_height
    width = (height * 16 // 9) // 2 * 2
    return width, height


def _letterbox_filter(width: int, height: int) -> str:
    content_h = int(width / CINEMASCOPE)
    bar = max((height - content_h) // 2, 0)
    if bar <= 0:
        return ""
    return (
        f"drawbox=x=0:y=0:w={width}:h={bar}:color=black:t=fill,"
        f"drawbox=x=0:y={height - bar}:w={width}:h={bar}:color=black:t=fill"
    )


def _shot_filters(opts: TrailerOptions, speed: float) -> str:
    width, height = _frame_size(opts)
    parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        f"fps={FPS}",
    ]
    if speed != 1.0:
        parts.append(f"setpts=PTS/{speed:.6g}")
    if opts.style.grade:
        parts.append(opts.style.grade)
    if opts.style.letterbox:
        lb = _letterbox_filter(width, height)
        if lb:
            parts.append(lb)
    parts.append("format=yuv420p")
    return ",".join(parts)


_ENCODE = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
    "-video_track_timescale", "90000",
]


def render_shot_segment(
    item: TimelineItem, source: str, has_audio: bool, opts: TrailerOptions, out_path: str
) -> None:
    assert item.start is not None and item.end is not None
    span = item.end - item.start
    vf = _shot_filters(opts, item.speed)

    args: list[str] = ["-ss", f"{item.start:.3f}", "-t", f"{span:.3f}", "-i", source]
    if has_audio:
        af = atempo_chain(item.speed) if item.speed != 1.0 else "anull"
        args += [
            "-vf", vf,
            "-af", af,
            "-map", "0:v:0", "-map", "0:a:0",
        ]
    else:
        args += [
            "-f", "lavfi", "-t", f"{span / item.speed:.3f}",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", vf,
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
        ]
    args += [*_ENCODE, out_path]
    run_ffmpeg(args, timeout=1800)


def render_title_segment(item: TimelineItem, opts: TrailerOptions, out_path: str) -> None:
    width, height = _frame_size(opts)
    duration = item.duration or 2.0
    fade = min(opts.style.card_fade, duration / 3)
    text = drawtext_escape(item.text or "")
    font = find_font()
    fontfile = f"fontfile={font}:" if font else ""
    vf = (
        f"drawtext={fontfile}text='{text}':fontcolor=white:"
        f"fontsize={opts.style.card_font_size}:x=(w-text_w)/2:y=(h-text_h)/2:"
        f"borderw=0,"
        f"fade=t=in:st=0:d={fade:.3f},fade=t=out:st={duration - fade:.3f}:d={fade:.3f},"
        f"format=yuv420p"
    )
    run_ffmpeg(
        [
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", f"color=black:s={width}x{height}:r={FPS}",
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", vf,
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            *_ENCODE,
            out_path,
        ],
        timeout=600,
    )


def _final_pass(assembled: str, total: float, opts: TrailerOptions, output: str) -> None:
    fade_start = max(total - 1.2, 0.0)
    vf = f"fade=t=out:st={fade_start:.3f}:d=1.2"

    if opts.music and os.path.exists(opts.music):
        music_fade_out = max(total - 2.5, 0.0)
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{total:.3f},"
            f"afade=t=in:st=0:d=1.0,afade=t=out:st={music_fade_out:.3f}:d=2.5,"
            f"volume=0.9[music];"
            # duck the music under the trailer's own audio (dialogue/impacts)
            f"[music][0:a]sidechaincompress=threshold=0.06:ratio=8:attack=25:release=600[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:normalize=0,"
            f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
        run_ffmpeg(
            [
                "-i", assembled,
                "-i", opts.music,
                "-filter_complex", filter_complex,
                "-map", "0:v:0", "-map", "[aout]",
                "-vf", vf,
                *_ENCODE,
                output,
            ],
            timeout=1800,
        )
    else:
        run_ffmpeg(
            [
                "-i", assembled,
                "-vf", vf,
                "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                *_ENCODE,
                output,
            ],
            timeout=1800,
        )


def render(plan: TrailerPlan, info: MediaInfo, opts: TrailerOptions, output: str) -> str:
    if not plan.timeline:
        raise RuntimeError("Trailer plan is empty; nothing to render")

    workdir = tempfile.mkdtemp(prefix="trailer_agent_")
    try:
        segments: list[str] = []
        for i, item in enumerate(plan.timeline):
            seg_path = os.path.join(workdir, f"seg_{i:03d}.mp4")
            if item.kind == "title":
                log.info("Rendering title card %d: %r", i, item.text)
                render_title_segment(item, opts, seg_path)
            else:
                log.info(
                    "Rendering shot %d: %.2f-%.2fs x%.2g (%s)",
                    i, item.start, item.end, item.speed, item.note or "-",
                )
                render_shot_segment(item, info.path, info.has_audio, opts, seg_path)
            segments.append(seg_path)

        concat_list = os.path.join(workdir, "concat.txt")
        with open(concat_list, "w") as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")

        assembled = os.path.join(workdir, "assembled.mp4")
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", assembled],
            timeout=600,
        )

        log.info("Final pass: mix, grade, loudness")
        _final_pass(assembled, plan.total_duration(), opts, output)
        return output
    finally:
        if opts.keep_temp:
            log.info("Keeping temp dir: %s", workdir)
        else:
            shutil.rmtree(workdir, ignore_errors=True)
