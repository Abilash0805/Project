"""Render a TrailerPlan into a finished mp4 with ffmpeg.

Strategy: every timeline item becomes a uniformly-encoded segment file
(same codec/size/fps/audio layout), segments are concatenated losslessly,
then a final pass adds music (started on its first beat and side-chain
ducked under the original audio), optional riser + hit sound design into
the title card, loudness normalization, and an end fade.
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
DECLICK = 0.03  # tiny audio fades at every cut so edits never click

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


def escape_filter_path(path: str) -> str:
    """Escape a filesystem path for use as a filter-graph option value.

    ffmpeg's filter parser treats '\\' and ':' as syntax, so a Windows font
    path like C:\\Windows\\Fonts\\arial.ttf breaks drawtext. ffmpeg accepts
    forward slashes on Windows, so normalize to '/' and escape the drive colon.
    On POSIX paths (no backslash, no colon) this is a no-op.
    """
    return path.replace("\\", "/").replace(":", "\\:")


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


def _shot_filters(opts: TrailerOptions, item: TimelineItem) -> str:
    width, height = _frame_size(opts)
    out_dur = item.output_duration()
    parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=decrease",
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
        f"fps={FPS}",
    ]
    if item.speed != 1.0:
        parts.append(f"setpts=PTS/{item.speed:.6g}")
    if opts.style.grade:
        parts.append(opts.style.grade)
    if opts.style.letterbox:
        lb = _letterbox_filter(width, height)
        if lb:
            parts.append(lb)
    if item.fade_in > 0:
        parts.append(f"fade=t=in:st=0:d={item.fade_in:.3f}")
    if item.fade_out > 0:
        parts.append(f"fade=t=out:st={max(out_dur - item.fade_out, 0):.3f}:d={item.fade_out:.3f}")
    parts.append("format=yuv420p")
    return ",".join(parts)


def _shot_audio_filters(item: TimelineItem) -> str:
    out_dur = item.output_duration()
    parts = []
    if item.speed != 1.0:
        parts.append(atempo_chain(item.speed))
    # de-click: micro fades at both edges of every cut
    parts.append(f"afade=t=in:st=0:d={DECLICK}")
    parts.append(f"afade=t=out:st={max(out_dur - DECLICK, 0):.3f}:d={DECLICK}")
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
    vf = _shot_filters(opts, item)

    args: list[str] = ["-ss", f"{item.start:.3f}", "-t", f"{span:.3f}", "-i", source]
    if has_audio:
        args += [
            "-vf", vf,
            "-af", _shot_audio_filters(item),
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


def render_card_segment(item: TimelineItem, opts: TrailerOptions, out_path: str) -> None:
    """A title card, or a bare dip-to-black when the item has no text."""
    width, height = _frame_size(opts)
    duration = item.duration or 2.0
    filters: list[str] = []
    if item.kind == "title" and item.text:
        fade = min(opts.style.card_fade, duration / 3)
        text = drawtext_escape(item.text)
        font = find_font()
        fontfile = f"fontfile={escape_filter_path(font)}:" if font else ""
        filters.append(
            f"drawtext={fontfile}text='{text}':fontcolor=white:"
            f"fontsize={opts.style.card_font_size}:x=(w-text_w)/2:y=(h-text_h)/2"
        )
        filters.append(f"fade=t=in:st=0:d={fade:.3f}")
        filters.append(f"fade=t=out:st={duration - fade:.3f}:d={fade:.3f}")
    filters.append("format=yuv420p")
    run_ffmpeg(
        [
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", f"color=black:s={width}x{height}:r={FPS}",
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-vf", ",".join(filters),
            "-map", "0:v:0", "-map", "1:a:0",
            "-shortest",
            *_ENCODE,
            out_path,
        ],
        timeout=600,
    )


# -- sound design -----------------------------------------------------------

def _title_start_time(plan: TrailerPlan) -> float | None:
    """Trailer-time offset where the first title card begins."""
    t = 0.0
    for item in plan.timeline:
        if item.kind == "title":
            return t
        t += item.output_duration()
    return None


def synth_riser(path: str, duration: float = 2.2) -> None:
    """Pink-noise riser that swells into the title card."""
    run_ffmpeg(
        [
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", f"anoisesrc=color=pink:amplitude=0.45:r=48000",
            "-af",
            f"highpass=f=180,afade=t=in:st=0:d={duration - 0.15:.3f}:curve=exp,"
            f"afade=t=out:st={duration - 0.12:.3f}:d=0.12",
            "-ac", "2",
            path,
        ],
        timeout=120,
    )


def synth_hit(path: str, duration: float = 1.6) -> None:
    """Decaying sub-bass boom on the title reveal."""
    run_ffmpeg(
        [
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", f"aevalsrc=0.85*sin(2*PI*48*t)*exp(-4*t):s=48000",
            "-af", f"afade=t=out:st={duration - 0.2:.3f}:d=0.2",
            "-ac", "2",
            path,
        ],
        timeout=120,
    )


def _final_pass(
    assembled: str,
    plan: TrailerPlan,
    opts: TrailerOptions,
    output: str,
    workdir: str,
) -> None:
    total = plan.total_duration()
    fade_start = max(total - 1.2, 0.0)
    vf = f"fade=t=out:st={fade_start:.3f}:d=1.2"

    inputs: list[str] = ["-i", assembled]
    filters: list[str] = []
    mix_labels: list[str] = ["[0:a]"]
    next_input = 1

    has_music = bool(opts.music and os.path.exists(opts.music))
    if has_music:
        inputs += ["-i", opts.music]
        music_fade_out = max(total - 2.5, 0.0)
        # start the track on its first detected beat so cuts land on the grid
        offset = getattr(opts, "music_offset", 0.0) or 0.0
        trim = f"atrim=start={offset:.3f},asetpts=PTS-STARTPTS," if offset > 0.01 else ""
        filters.append(
            f"[{next_input}:a]{trim}aloop=loop=-1:size=2e9,atrim=0:{total:.3f},"
            f"afade=t=in:st=0:d=1.0,afade=t=out:st={music_fade_out:.3f}:d=2.5,"
            f"volume=0.9[music]"
        )
        # duck the music under the trailer's own audio (dialogue/impacts)
        filters.append(
            "[music][0:a]sidechaincompress="
            "threshold=0.06:ratio=8:attack=25:release=600[ducked]"
        )
        mix_labels.append("[ducked]")
        next_input += 1

    title_at = _title_start_time(plan)
    if opts.sfx and title_at is not None and title_at > 0.5:
        riser_path = os.path.join(workdir, "riser.wav")
        hit_path = os.path.join(workdir, "hit.wav")
        riser_len = min(2.2, title_at)
        synth_riser(riser_path, riser_len)
        synth_hit(hit_path)

        riser_ms = int(max(title_at - riser_len, 0.0) * 1000)
        hit_ms = int(title_at * 1000)
        inputs += ["-i", riser_path, "-i", hit_path]
        filters.append(f"[{next_input}:a]volume=0.5,adelay={riser_ms}|{riser_ms}[riser]")
        filters.append(f"[{next_input + 1}:a]volume=0.8,adelay={hit_ms}|{hit_ms}[hit]")
        mix_labels += ["[riser]", "[hit]"]
        next_input += 2

    if len(mix_labels) > 1:
        filters.append(
            f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:"
            f"duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        )
        run_ffmpeg(
            [
                *inputs,
                "-filter_complex", ";".join(filters),
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
                *inputs,
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
    source = os.path.abspath(info.path)  # resolvable regardless of cwd
    try:
        segments: list[str] = []
        for i, item in enumerate(plan.timeline):
            seg_name = f"seg_{i:03d}.mp4"
            seg_path = os.path.join(workdir, seg_name)
            if item.kind in ("title", "black"):
                log.info("Rendering %s card %d: %r", item.kind, i, item.text or "")
                render_card_segment(item, opts, seg_path)
            else:
                log.info(
                    "Rendering shot %d: %.2f-%.2fs x%.2g (%s)",
                    i, item.start, item.end, item.speed, item.note or "-",
                )
                render_shot_segment(item, source, info.has_audio, opts, seg_path)
            segments.append(seg_name)

        # The concat demuxer treats '\' as an escape character, so absolute
        # Windows paths (C:\...\seg.mp4) get corrupted. List the segments by
        # bare filename and run concat from `workdir` (cwd) so they resolve.
        concat_list = os.path.join(workdir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(f"file '{seg}'\n")

        assembled = os.path.join(workdir, "assembled.mp4")
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "assembled.mp4"],
            timeout=600,
            cwd=workdir,
        )

        log.info("Final pass: music, sound design, loudness")
        _final_pass(assembled, plan, opts, output, workdir)
        return output
    finally:
        if opts.keep_temp:
            log.info("Keeping temp dir: %s", workdir)
        else:
            shutil.rmtree(workdir, ignore_errors=True)
