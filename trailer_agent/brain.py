"""The editorial brain: Claude plans the trailer; a heuristic editor is the fallback."""

from __future__ import annotations

import logging
import os

from .analysis import VideoAnalysis
from .config import TrailerOptions
from .storyboard import TimelineItem, TrailerPlan, validate_plan

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a world-class movie trailer editor. You receive an analysis of a long video
(scene table with timestamps, loudness "energy" 0-1, visual cut intensity, and
transcript snippets when available) and you produce a trailer plan.

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


def plan_heuristic(analysis: VideoAnalysis, opts: TrailerOptions) -> TrailerPlan:
    """Signal-driven fallback editor: no API required.

    Builds hook -> setup -> build -> montage -> breath -> title -> button from the
    energy curve, with shot lengths that shrink as the trailer accelerates.
    """
    scenes = [s for s in analysis.scenes if s.duration >= 1.0]
    if not scenes:
        scenes = analysis.scenes[:]
    if not scenes:
        raise RuntimeError("No usable scenes found in the video")

    duration = analysis.info.duration
    by_energy = sorted(scenes, key=lambda s: (s.peak, s.energy), reverse=True)
    used: set[int] = set()

    def take(candidates, want, *, min_gap=8.0):
        picked = []
        for scene in candidates:
            key = id(scene)
            if key in used:
                continue
            if any(abs(scene.start - p.start) < min_gap for p in picked):
                continue
            picked.append(scene)
            used.add(key)
            if len(picked) >= want:
                break
        return picked

    def clip(scene, length, *, speed=1.0, note=""):
        # cut from the loudest-adjacent middle of the scene, not the edges
        span = min(length * speed, scene.duration)
        mid = scene.start + scene.duration / 2
        start = max(scene.start, min(mid - span / 2, scene.end - span))
        return TimelineItem(kind="shot", start=round(start, 2),
                            end=round(start + span, 2), speed=speed, note=note)

    target = opts.target_duration
    timeline: list[TimelineItem] = []

    # 1. hook: single most intense moment
    hook = take(by_energy, 1)
    if hook:
        timeline.append(clip(hook[0], 3.0, note="hook: peak energy"))

    # 2. setup: 2-3 calm scenes from the first third, longer shots
    first_third = [s for s in scenes if s.end < duration / 3]
    calm = sorted(first_third, key=lambda s: s.energy)
    for scene in take(calm, 3, min_gap=12.0):
        timeline.append(clip(scene, 4.0, note="setup"))

    # 3. build: mid-energy scenes across the middle, medium shots
    middle = [s for s in scenes if duration / 4 < s.start < duration * 0.85]
    mid_energy = sorted(middle, key=lambda s: abs(s.energy - 0.6))
    for scene in take(mid_energy, 3, min_gap=10.0):
        timeline.append(clip(scene, 2.5, note="build"))

    # 4. montage: high-energy everywhere, short accelerating shots
    montage_lengths = [1.6, 1.3, 1.1, 0.9, 0.8]
    for i, scene in enumerate(take(by_energy, len(montage_lengths), min_gap=6.0)):
        timeline.append(clip(scene, montage_lengths[i], note=f"montage {i + 1}"))

    # 5. the breath: quietest scene, slowed down
    quiet = sorted(scenes, key=lambda s: s.energy)
    breath = take(quiet, 1)
    if breath:
        timeline.append(clip(breath[0], 2.2, speed=0.7, note="breath"))

    # 6. title card(s)
    if opts.title:
        timeline.append(TimelineItem(kind="title", text=opts.title.upper(),
                                     duration=2.6, note="title"))
    if opts.tagline:
        timeline.append(TimelineItem(kind="title", text=opts.tagline,
                                     duration=2.0, note="tagline"))

    # 7. button: one last punchy beat
    button = take(by_energy, 1)
    if button:
        timeline.append(clip(button[0], 1.4, note="button"))

    plan = TrailerPlan(
        logline=f"Heuristic {opts.style.name} cut: energy-driven highlights",
        timeline=timeline,
    )
    return plan


def make_plan(analysis: VideoAnalysis, opts: TrailerOptions) -> TrailerPlan:
    plan: TrailerPlan | None = None
    if opts.use_ai and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            plan = plan_with_claude(analysis, opts)
        except Exception as exc:
            log.warning("Claude planning failed (%s); falling back to heuristic editor", exc)
    elif opts.use_ai:
        log.warning("ANTHROPIC_API_KEY not set; using the heuristic editor. "
                    "Set the key to get AI editorial decisions.")
    if plan is None:
        plan = plan_heuristic(analysis, opts)
    return validate_plan(plan, analysis.info.duration, opts.target_duration)
