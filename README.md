# trailer-agent 🎬

An AI agent that turns a **15–20 minute video** into a **next-level cinematic trailer**.

Point it at a long video and it analyzes every scene, understands what's exciting,
and cuts a trailer with real trailer grammar: a cold-open hook, a setup, a rising
build, an accelerating montage, a breath of silence, your title card, and a final
button shot.

```
┌──────────┐   ┌─────────┐   ┌─────────┐   ┌────────────┐   ┌─────────┐   ┌────────┐
│  probe    │→│  scenes  │→│  audio   │→│ transcript  │→│  brain   │→│ render  │
│ (ffprobe) │  │ (cuts)   │  │ (energy) │  │ (optional)  │  │ (Claude) │  │ (ffmpeg)│
└──────────┘   └─────────┘   └─────────┘   └────────────┘   └─────────┘   └────────┘
```

## How it works

1. **Probe** — reads duration, resolution, and fps with ffprobe.
2. **Scene detection** — ffmpeg's scene-score filter finds every hard cut; slivers
   are merged, marathon scenes are split.
3. **Audio energy** — per-half-second loudness becomes an "excitement" curve; every
   scene gets an energy and peak score.
4. **Transcript (optional)** — if [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper)
   is installed, dialogue is transcribed and attached to scenes, so the AI editor
   can pick quotable lines.
5. **The brain** — Claude (default: `claude-opus-4-8`) receives the compact scene
   table and acts as a trailer editor: it picks moments, decides pacing and slow-mo,
   writes title cards, and returns a structured, validated plan.
   No API key? A built-in **heuristic editor** cuts a solid energy-driven trailer.
6. **Render** — ffmpeg cuts each shot frame-accurately, applies a style grade and
   cinematic 2.39:1 letterbox, renders fading title cards, concatenates everything,
   side-chain-ducks your music under the dialogue, normalizes loudness to -14 LUFS,
   and fades out.

## Install

```bash
# ffmpeg is required
sudo apt install ffmpeg        # or: brew install ffmpeg

pip install -e .               # core
pip install -e ".[transcribe]" # + speech-to-text (recommended)

export ANTHROPIC_API_KEY=sk-ant-...   # enables the AI editor
```

## Usage

```bash
# The one-liner: 60-second epic trailer
trailer-agent make my_video.mp4 -o trailer.mp4 --title "THE LAST RUN"

# Full control
trailer-agent make my_video.mp4 -o trailer.mp4 \
    --duration 75 \
    --style action \
    --title "THE LAST RUN" \
    --tagline "One shot. No second chances." \
    --music epic_track.mp3

# No API key / offline: heuristic editor
trailer-agent make my_video.mp4 --no-ai --title "MY FILM"

# Inspect before you render
trailer-agent analyze my_video.mp4            # scene/energy table as JSON
trailer-agent plan my_video.mp4 -o plan.json  # editorial plan as JSON
# ...edit plan.json by hand if you like...
trailer-agent render my_video.mp4 --plan plan.json -o trailer.mp4
```

`python -m trailer_agent ...` works too if you haven't installed the entry point.

### Styles

| Style       | Feel                                                          |
|-------------|---------------------------------------------------------------|
| `epic`      | Sweeping blockbuster: slow open, rising tension, big title    |
| `action`    | Punchy and relentless: short shots, hard cuts, peak energy    |
| `emotional` | Intimate: longer shots, dialogue-forward, soft ending         |
| `minimal`   | Restrained: few shots, negative space, confident silence      |

### Key flags

| Flag                | Default           | What it does                              |
|---------------------|-------------------|-------------------------------------------|
| `--duration`        | `60`              | Target trailer length (seconds)           |
| `--style`           | `epic`            | Visual + pacing style                     |
| `--music PATH`      | –                 | Music bed, auto-ducked under dialogue     |
| `--no-ai`           | off               | Use the heuristic editor (no API calls)   |
| `--model`           | `claude-opus-4-8` | Claude model for editorial planning       |
| `--scene-threshold` | `0.27`            | Lower = more cuts detected                |
| `--height`          | `1080`            | Output resolution height                  |

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite covers ffmpeg-output parsing, plan validation, the heuristic
editor, and renderer helpers — no ffmpeg binary or API key needed to run it.

## Notes

- The Claude editor uses [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
  so the plan always validates against the `TrailerPlan` schema; timestamps are
  additionally clamped against the real video duration before rendering.
- Every plan is renderable offline: `plan` → tweak JSON → `render` is a fully
  reproducible pipeline.
- Long inputs are fine — analysis streams through ffmpeg without loading video
  into memory.
