"""Command-line interface for trailer-agent."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .analysis import analyze
from .brain import make_plan
from .config import DEFAULT_MODEL, STYLES, TrailerOptions
from .music import BeatGrid, analyze_music
from .render import render
from .storyboard import TrailerPlan, validate_plan


def _build_options(args: argparse.Namespace) -> TrailerOptions:
    return TrailerOptions(
        target_duration=args.duration,
        style=STYLES[args.style],
        title=args.title,
        tagline=args.tagline,
        music=args.music,
        use_ai=not args.no_ai,
        model=args.model,
        output_height=args.height,
        keep_temp=args.keep_temp,
        sfx=not args.no_sfx,
    )


def _music_grid(opts: TrailerOptions) -> BeatGrid | None:
    """Detect the music's beat grid and remember its first-beat offset."""
    if not opts.music:
        return None
    grid = analyze_music(opts.music)
    if grid:
        opts.music_offset = grid.first_beat
    return grid


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("input", help="Path to the source video (15-20 min works great)")
    p.add_argument("--duration", type=float, default=60.0,
                   help="Target trailer length in seconds (default: 60)")
    p.add_argument("--style", choices=sorted(STYLES), default="epic",
                   help="Trailer style (default: epic)")
    p.add_argument("--title", default="", help="Title card text")
    p.add_argument("--tagline", default="", help="Tagline card text")
    p.add_argument("--music", default="", help="Optional music track to mix under the cut")
    p.add_argument("--no-ai", action="store_true",
                   help="Skip Claude and use the built-in heuristic editor")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=f"Claude model for editorial planning (default: {DEFAULT_MODEL})")
    p.add_argument("--no-transcript", action="store_true",
                   help="Skip speech-to-text even if faster-whisper is installed")
    p.add_argument("--scene-threshold", type=float, default=0.27,
                   help="Scene-cut sensitivity 0-1; lower finds more cuts (default: 0.27)")
    p.add_argument("--height", type=int, default=1080, help="Output height (default: 1080)")
    p.add_argument("--keep-temp", action="store_true", help="Keep intermediate segment files")
    p.add_argument("--no-sfx", action="store_true",
                   help="Disable the synthesized riser + hit into the title card")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="trailer-agent",
        description="AI agent that cuts a long video into a cinematic trailer.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_make = sub.add_parser("make", help="Analyze, plan, and render the trailer (full pipeline)")
    _add_common(p_make)
    p_make.add_argument("-o", "--output", default="trailer.mp4", help="Output file")

    p_analyze = sub.add_parser("analyze", help="Print the scene/energy analysis as JSON")
    _add_common(p_analyze)

    p_plan = sub.add_parser("plan", help="Produce the trailer plan as JSON without rendering")
    _add_common(p_plan)
    p_plan.add_argument("-o", "--output", default="", help="Write plan JSON here (default: stdout)")

    p_render = sub.add_parser("render", help="Render a previously saved plan JSON")
    _add_common(p_render)
    p_render.add_argument("--plan", required=True, help="Path to plan JSON from `plan`")
    p_render.add_argument("-o", "--output", default="trailer.mp4", help="Output file")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("trailer_agent")

    opts = _build_options(args)

    if args.command == "analyze":
        result = analyze(args.input, scene_threshold=args.scene_threshold,
                         with_transcript=not args.no_transcript)
        print(result.to_compact_json())
        return 0

    if args.command == "plan":
        result = analyze(args.input, scene_threshold=args.scene_threshold,
                         with_transcript=not args.no_transcript)
        plan = make_plan(result, opts, grid=_music_grid(opts))
        payload = plan.model_dump_json(indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(payload)
            log.info("Plan written to %s (%.1fs total)", args.output, plan.total_duration())
        else:
            print(payload)
        return 0

    if args.command == "render":
        from .probe import probe

        info = probe(args.input)
        _music_grid(opts)  # sets opts.music_offset for beat-aligned music start
        with open(args.plan) as f:
            plan = TrailerPlan.model_validate(json.load(f))
        plan = validate_plan(plan, info.duration, opts.target_duration)
        out = render(plan, info, opts, args.output)
        log.info("Trailer written to %s", out)
        return 0

    # make: full pipeline
    result = analyze(args.input, scene_threshold=args.scene_threshold,
                     with_transcript=not args.no_transcript)
    plan = make_plan(result, opts, grid=_music_grid(opts))
    log.info("Plan: %s — %d items, %.1fs", plan.logline or "(untitled)",
             len(plan.timeline), plan.total_duration())
    for item in plan.timeline:
        if item.kind == "shot":
            log.info("  shot  %7.2f-%7.2fs x%.2g  %s", item.start, item.end,
                     item.speed, item.note)
        elif item.kind == "black":
            log.info("  black (%.2fs)  %s", item.duration or 0.3, item.note)
        else:
            log.info("  title %r (%.1fs)", item.text, item.duration or 2.0)
    out = render(plan, result.info, opts, args.output)
    log.info("Trailer written to %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
