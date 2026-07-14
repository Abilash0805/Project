# trailer-agent 🎬

An AI agent that turns a **15–20 minute video** into a **next-level cinematic trailer** —
**no API key required**.

Point it at a long video and it analyzes every scene, understands what's exciting,
and cuts a trailer with real trailer grammar: a cold-open hook, a setup, a rising
build, an accelerating montage, a breath of silence, your title card, and a final
button shot.

```
┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌───────────┐   ┌────────┐
│  probe    │→│ scene + motion │→│ loudness +    │→│ pro editor │→│ render  │
│ (ffprobe) │  │ + fingerprints │  │ speech (1 pass)│  │ (offline)  │  │ (ffmpeg)│
└──────────┘   └──────────────┘   └──────────────┘   └───────────┘   └────────┘
```

## The built-in pro editor (default — works fully offline)

The editor cuts like a professional, using nothing but ffmpeg and pure Python:

- **Beat-synced cutting** — give it a music track and it detects the BPM and beat
  grid (onset-flux autocorrelation), then quantizes every cut so it lands on the
  beat. The music itself starts on its first detected beat. Title card hits a downbeat.
- **Excitement scoring** — every scene is scored on a composite of loudness,
  visual motion (frame-difference analysis), and audio peaks. The hook and montage
  come from the top of that curve; the setup and breath from the bottom.
- **Speech-safe cuts** — silence detection finds phrase boundaries, and dialogue
  shots snap to them so nobody ever gets cut off mid-word.
- **No visual repetition** — 8×8 grayscale fingerprints of every second of footage
  mean the editor avoids picking two shots that look alike (and never reuses a
  single frame of footage).
- **Real trailer rhythm** — act structure with designed, non-monotonic shot-length
  patterns; the montage accelerates (2-beat → 1-beat flash cuts); dip-to-black
  transitions land between acts, one beat long when music is present.
- **Sound design** — a synthesized pink-noise riser swells into the title card and
  a sub-bass hit lands on the reveal (`--no-sfx` to disable); micro-fades at every
  cut so edits never click; music is side-chain ducked under dialogue; the final
  mix is loudness-normalized to -14 LUFS.

## Optional: Claude as the editor

If you *do* have an `ANTHROPIC_API_KEY`, Claude (default `claude-opus-4-8`) takes
over the editorial decisions — reading the scene table and transcript like a human
editor, picking quotable dialogue, and writing interstitial title cards. Everything
it returns is schema-validated and clamped against the real video before rendering.
Without a key, the pro editor above runs automatically. There is no functional
difference in the render pipeline.

## Install

```bash
# ffmpeg is required
sudo apt install ffmpeg        # or: brew install ffmpeg

pip install -e .               # core
pip install -e ".[transcribe]" # + local speech-to-text (recommended, still offline)
```

## Usage

```bash
# The one-liner: 60-second epic trailer
trailer-agent make my_video.mp4 -o trailer.mp4 --title "THE LAST RUN"

# The full experience: beat-synced to your music, with sound design
trailer-agent make my_video.mp4 -o trailer.mp4 \
    --duration 75 \
    --style action \
    --title "THE LAST RUN" \
    --tagline "One shot. No second chances." \
    --music epic_track.mp3

# Inspect before you render
trailer-agent analyze my_video.mp4            # scene/energy/motion table as JSON
trailer-agent plan my_video.mp4 -o plan.json  # editorial plan as JSON
# ...edit plan.json by hand if you like...
trailer-agent render my_video.mp4 --plan plan.json --music epic_track.mp3 -o trailer.mp4
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
| `--music PATH`      | –                 | Music bed: beat-synced cuts + auto-ducking |
| `--no-sfx`          | off               | Disable the riser + hit into the title    |
| `--no-ai`           | off               | Force the pro editor even with a key set  |
| `--model`           | `claude-opus-4-8` | Claude model when a key is available      |
| `--scene-threshold` | `0.27`            | Lower = more cuts detected                |
| `--height`          | `1080`            | Output resolution height                  |

## How the analysis works

Everything comes from **two ffmpeg decode passes**, no matter how long the video:

1. **Video pass** (downscaled): scene-change scores → cut list; `signalstats`
   frame-difference → motion curve; 1 fps 8×8 grayscale stream → visual fingerprints.
2. **Audio pass**: half-second RMS windows → excitement curve; `silencedetect` →
   speech regions.

If [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) is installed, a
third (optional, still local) pass transcribes dialogue so scenes carry quotable text.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite (38 tests) covers ffmpeg-output parsing, beat detection, plan
validation, speech-safe snapping, fingerprint dedupe, the pro editor's act
structure, and renderer helpers — no ffmpeg binary or API key needed to run it.
