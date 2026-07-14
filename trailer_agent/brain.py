"""The editorial brain: the built-in pro editor plans the trailer; Claude can
optionally take over the editorial decisions when an API key is available."""

from __future__ import annotations

import logging
import os

from .analysis import VideoAnalysis
from .config import TrailerOptions
from .editor import plan_professional
from .music import BeatGrid
from .storyboard import TimelineItem, TrailerPlan, validate_plan

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a world-class movie trailer editor. You receive an analysis of a long video
(scene table with timestamps, loudness "energy" 0-1, visual "motion" 0-1, cut
intensity, speech flags, and transcript snippets when available) and you produce a
trailer plan.

Trailer grammar you follow:
1. COLD OPEN / HOOK — open on the single most arresting 2-4 seconds. Grab instantly.
2. SETUP — a few calmer, longer shots that establish world/subject (use dialogue-rich
   scenes when transcript is available).
3. BUILD — rising energy, shots get shorter, stakes escalate.
4. MONTAGE — rapid-fire peak-energy moments, accelerating cuts (0.8-1.5s each).
5. THE BREATH — one quiet beat (a slow or low-energy moment) right before the title.
6. TITLE CARD — the title, then optionally a final "button": one last punchy shot
   or funny/striking beat after the title.

Rules:
- Only use timestamps that exist inside scenes from the analysis. Never invent times.
- Cut INTO the middle of scenes for the strongest micro-moment; you don't have to use
  a scene from its exact start.
- Never reuse the same footage twice.
- Respect chronology loosely in SETUP (avoid spoiling endings) but montage may jump.
- Slow motion (speed 0.5-0.8) for dramatic beats, mild speed-up (1.2-1.6) inside the
  montage is allowed. Default speed is 1.0.
- Title cards: short, ALL-CAPS lines work best. Use the provided title/tagline; write
  1-2 extra interstitial cards ONLY if they sharpen the narrative.
- You may insert `kind: "black"` items (duration 0.2-0.5s) as dip-to-black beats
  between acts — a classic trailer transition.
- Prefer scenes marked with speech for the SETUP act, and cut them generously so
  sentences are not clipped mid-word.
- The total output duration (sum of shot durations divided by speed, plus card
  durations) must land within 10% of the requested target.
- Fill `note` on each shot with a 3-8 word reason ("hook: loudest impact", "breath").
"""


def plan_with_claude(analysis: VideoAnalysis, opts: TrailerOptions) -> TrailerPlan:
    import anthropic

    client = anthropic.Anthropic()

    user_prompt = (
        f"Style: {opts.style.name} — {opts.style.description}\n"
        f"Target trailer duration: {opts.target_duration:.0f} seconds.\n"
        f"Title card text: {opts.title or '(none provided — do not invent one)'}\n"
        f"Tagline: {opts.tagline or '(none)'}\n\n"
        f"Video analysis:\n{analysis.to_compact_json()}"
    )

    response = client.messages.parse(
        model=opts.model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_format=TrailerPlan,
    )
    plan = response.parsed_output
    if plan is None:
        raise RuntimeError("Claude returned an unparseable trailer plan")
    log.info("Claude plan: %s (%d items, %.1fs)", plan.logline, len(plan.timeline),
             plan.total_duration())
    return plan


def make_plan(
    analysis: VideoAnalysis,
    opts: TrailerOptions,
    grid: BeatGrid | None = None,
) -> TrailerPlan:
    plan: TrailerPlan | None = None
    if opts.use_ai and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            plan = plan_with_claude(analysis, opts)
        except Exception as exc:
            log.warning("Claude planning failed (%s); using the built-in pro editor", exc)
    elif opts.use_ai:
        log.info("No ANTHROPIC_API_KEY found — using the built-in pro editor "
                 "(beat-synced, speech-safe, motion-aware; no API needed).")
    if plan is None:
        plan = plan_professional(analysis, opts, grid)
    return validate_plan(plan, analysis.info.duration, opts.target_duration)
