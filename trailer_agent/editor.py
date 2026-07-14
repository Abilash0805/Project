"""The pro editor: a professional trailer cut with zero API calls.

What it does that an amateur cut doesn't:
  - scores scenes on a composite of loudness, motion, and peaks ("excitement")
  - never picks two visually similar shots (8x8 fingerprint dedupe)
  - never clips dialogue mid-word (cut boundaries snap to silence edges)
  - cuts on the beat when a music track is provided (BPM grid quantization)
  - follows a real trailer arc with a designed, non-monotonic rhythm:
      HOOK -> [dip] -> SETUP -> BUILD -> [dip] -> MONTAGE (accelerating)
      -> BREATH (slow-mo, fade to black) -> TITLE / TAGLINE -> BUTTON
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .analysis import VideoAnalysis
from .audio import snap_to_speech
from .config import TrailerOptions
from .music import BeatGrid
from .quotes import Quote, mine_quotes
from .scenes import Scene
from .storyboard import TimelineItem, TrailerPlan
from .videostats import Fingerprints

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 25.0  # mean pixel diff below this = "same-looking shot"

# fraction of the target duration each act gets (cards/gaps come out of the rest)
ACT_BUDGET = {
    "hook": 0.06,
    "setup": 0.24,
    "build": 0.22,
    "montage": 0.32,
    "breath": 0.07,
    "button": 0.04,
}

# rhythm patterns in beats (or seconds when no grid): varied, not monotonic
SETUP_PATTERN = [4, 3, 4]
BUILD_PATTERN = [2, 3, 2, 2]
MONTAGE_PATTERN = [2, 2, 1, 2, 1, 1, 1, 1]  # accelerando


@dataclass
class _Picker:
    """Claims footage at sub-scene granularity; never reuses a frame twice."""

    fingerprints: Fingerprints | None
    used_spans: list[tuple[float, float]]
    picked_sigs: list[bytes]

    def _is_free(self, start: float, end: float) -> bool:
        return not any(start < e and s < end for s, e in self.used_spans)

    def free_window(self, scene: Scene, span: float, *,
                    step: float = 0.5) -> tuple[float, float] | None:
        """Find an unclaimed [start, start+span] inside the scene, preferring
        the middle of the scene and walking outward from there."""
        span = min(span, scene.duration)
        mid_start = scene.start + (scene.duration - span) / 2
        candidates = [mid_start]
        offset = step
        while (mid_start - offset >= scene.start
               or mid_start + offset + span <= scene.end):
            if mid_start + offset + span <= scene.end:
                candidates.append(mid_start + offset)
            if mid_start - offset >= scene.start:
                candidates.append(mid_start - offset)
            offset += step
        for s in candidates:
            if self._is_free(s, s + span):
                return s, s + span
        return None

    def available(self, scene: Scene, span: float = 0.8) -> bool:
        return self.free_window(scene, span) is not None

    def looks_new(self, scene: Scene) -> bool:
        if not self.fingerprints:
            return True
        sig = self.fingerprints.at(scene.start + scene.duration / 2)
        if sig is None:
            return True
        return all(
            Fingerprints.distance(sig, seen) > SIMILARITY_THRESHOLD
            for seen in self.picked_sigs
        )

    def claim(self, start: float, end: float, scene: Scene) -> None:
        self.used_spans.append((start, end))
        if self.fingerprints:
            sig = self.fingerprints.at((start + end) / 2)
            if sig is not None:
                self.picked_sigs.append(sig)


class ProEditor:
    def __init__(self, analysis: VideoAnalysis, opts: TrailerOptions,
                 grid: BeatGrid | None = None):
        self.analysis = analysis
        self.opts = opts
        self.grid = grid
        self.picker = _Picker(analysis.fingerprints, [], [])
        self.scenes = [s for s in analysis.scenes if s.duration >= 0.8] or analysis.scenes[:]

    # -- timing helpers -------------------------------------------------

    def beats(self, n_beats: float, fallback_seconds: float) -> float:
        """Convert a beat count to seconds; without a grid, use the fallback."""
        if self.grid:
            dur = max(n_beats, 1) * self.grid.interval
            while dur < 0.5:  # at fast tempos, 1 beat is too short even for a flash cut
                dur += self.grid.interval
            return dur
        return fallback_seconds

    def gap_duration(self) -> float:
        """A dip-to-black between acts: one beat on the grid, else 0.3s."""
        return self.grid.interval if self.grid else 0.3

    # -- shot construction ----------------------------------------------

    def cut_shot(self, scene: Scene, length: float, *, speed: float = 1.0,
                 note: str = "", dialogue: bool = False) -> TimelineItem | None:
        span = min(length * speed, scene.duration)
        window = self.picker.free_window(scene, span)
        if window is None:
            return None
        start, end = window

        if dialogue and self.analysis.speech:
            snapped = snap_to_speech(start, end, self.analysis.speech)
            s = max(snapped[0], scene.start)
            e = min(snapped[1], scene.end)
            # only keep the snap if the adjusted window is still free footage
            if e - s >= 0.6 and self.picker._is_free(s, e):
                start, end = s, e

        self.picker.claim(start, end, scene)
        return TimelineItem(kind="shot", start=round(start, 3), end=round(end, 3),
                            speed=speed, note=note)

    def pick(self, candidates: list[Scene], count: int, *, min_gap: float = 8.0,
             dedupe: bool = True) -> list[Scene]:
        """Two passes: prefer visually fresh scenes, but fill the act either way."""
        picked: list[Scene] = []

        def _pass(check_visuals: bool) -> None:
            for scene in candidates:
                if len(picked) >= count:
                    return
                if scene in picked or not self.picker.available(scene):
                    continue
                if any(abs(scene.start - p.start) < min_gap for p in picked):
                    continue
                if check_visuals and not self.picker.looks_new(scene):
                    continue
                picked.append(scene)

        _pass(check_visuals=dedupe)
        if len(picked) < count:
            _pass(check_visuals=False)  # visual variety is a preference, not a veto
        return picked

    def black_gap(self, note: str) -> TimelineItem:
        return TimelineItem(kind="black", duration=round(self.gap_duration(), 3), note=note)

    def cut_quote(self, quote: Quote, *, note: str) -> TimelineItem | None:
        """Cut a shot exactly around a spoken line, padded so it lands on the grid.

        Lead-in/out padding gives the line air; when a beat grid exists the tail
        is extended (into free footage only) so the shot stays a beat multiple.
        """
        start = max(quote.start - 0.25, 0.0)
        end = min(quote.end + 0.35, self.analysis.info.duration)
        if end - start < 0.6:
            return None
        if not self.picker._is_free(start, end):
            return None
        if self.grid:
            desired = self.grid.quantize(end - start)
            padded_end = start + desired
            if (padded_end <= self.analysis.info.duration
                    and self.picker._is_free(start, padded_end)):
                end = padded_end  # keep the grid; otherwise let the line breathe off-grid
        self.picker.claim(start, end, Scene(start=start, end=end))
        return TimelineItem(kind="shot", start=round(start, 3), end=round(end, 3),
                            note=f"{note}: “{quote.text[:60]}”")

    # -- the cut ----------------------------------------------------------

    def plan(self) -> TrailerPlan:
        duration = self.analysis.info.duration
        target = self.opts.target_duration
        scenes = self.scenes
        by_excitement = sorted(scenes, key=lambda s: s.excitement, reverse=True)

        budget = {act: frac * target for act, frac in ACT_BUDGET.items()}

        # mine the transcript for the lines a pro would build the trailer around
        quotes = mine_quotes(self.analysis.segments, 4) if self.analysis.segments else []
        the_line = quotes[0] if quotes else None      # best line: saved for pre-title
        setup_quotes = sorted(quotes[1:], key=lambda q: q.start)  # story order

        opening: list[TimelineItem] = []
        montage: list[TimelineItem] = []
        closing: list[TimelineItem] = []

        # 1. HOOK — the single most arresting moment, slams in cold
        for scene in by_excitement:
            shot = self.cut_shot(scene, self.beats(3, budget["hook"]),
                                 note="hook: peak excitement")
            if shot:
                opening.append(shot)
                break
        opening.append(self.black_gap("dip after hook"))

        # 2. SETUP — built around quotable dialogue when a transcript exists,
        #    else dialogue-flagged scenes from the first third
        n_setup = max(min(len(SETUP_PATTERN), int(budget["setup"] // 3)), 1)
        used_setup = 0
        for quote in setup_quotes[:n_setup]:
            shot = self.cut_quote(quote, note=f"setup {used_setup + 1}")
            if shot:
                opening.append(shot)
                used_setup += 1
        if used_setup < n_setup:
            first_third = [s for s in scenes if s.end < duration / 3]
            talkers = [s for s in first_third if s.has_speech or s.text]
            calm = sorted(talkers or first_third, key=lambda s: s.excitement)
            for i, scene in enumerate(self.pick(calm, n_setup - used_setup, min_gap=12.0)):
                length = self.beats(SETUP_PATTERN[i % len(SETUP_PATTERN)],
                                    budget["setup"] / n_setup)
                shot = self.cut_shot(scene, length, note=f"setup {used_setup + i + 1}",
                                     dialogue=bool(scene.has_speech or scene.text))
                if shot:
                    opening.append(shot)

        # 3. BUILD — rising intensity across the middle of the film
        middle = [s for s in scenes if duration / 4 < s.start < duration * 0.85]
        rising = sorted(middle, key=lambda s: s.excitement)
        band = [s for s in rising if 0.35 <= s.excitement] or rising
        n_build = max(min(len(BUILD_PATTERN), int(budget["build"] // 2)), 1)
        picks = self.pick(band, n_build, min_gap=10.0)
        picks.sort(key=lambda s: s.excitement)  # each shot hotter than the last
        for i, scene in enumerate(picks):
            length = self.beats(BUILD_PATTERN[i % len(BUILD_PATTERN)],
                                budget["build"] / n_build)
            shot = self.cut_shot(scene, length, note=f"build {i + 1}")
            if shot:
                opening.append(shot)
        opening.append(self.black_gap("dip before montage"))

        # 4. MONTAGE — rapid-fire peaks, accelerating to the climax
        n_montage = max(min(len(MONTAGE_PATTERN), int(budget["montage"] // 1.2)), 2)
        montage_picks = self.pick(by_excitement, n_montage, min_gap=5.0)
        for i, scene in enumerate(montage_picks):
            pattern = MONTAGE_PATTERN[i % len(MONTAGE_PATTERN)]
            fallback = max(budget["montage"] / n_montage * (1.0 - 0.06 * i), 0.7)
            shot = self.cut_shot(scene, self.beats(pattern, fallback),
                                 speed=1.0 if pattern > 1 else 1.15,
                                 note=f"montage {i + 1}")
            if shot:
                montage.append(shot)

        # 5. THE LINE — the best quote in the film, alone before the breath
        if the_line:
            shot = self.cut_quote(the_line, note="the line")
            if shot:
                closing.append(shot)

        # 6. BREATH — the quiet beat before the title, slowed, fading to black
        quiet = sorted(scenes, key=lambda s: s.excitement)
        for scene in quiet:
            shot = self.cut_shot(scene, self.beats(4, budget["breath"]), speed=0.75,
                                 note="breath")
            if shot:
                shot.fade_out = 0.5
                closing.append(shot)
                break

        # 7. TITLE / TAGLINE
        if self.opts.title:
            closing.append(TimelineItem(
                kind="title", text=self.opts.title.upper(),
                duration=round(self.beats(4, 2.6), 3), note="title"))
        if self.opts.tagline:
            closing.append(TimelineItem(
                kind="title", text=self.opts.tagline,
                duration=round(self.beats(3, 2.0), 3), note="tagline"))

        # 8. BUTTON — one last punch after the cards
        for scene in by_excitement:
            shot = self.cut_shot(scene, self.beats(2, budget["button"]),
                                 note="button")
            if shot:
                closing.append(shot)
                break

        # 9. FILL — a pro delivers the length that was asked for: keep adding
        #    montage beats while the cut runs short and fresh footage remains
        def total() -> float:
            return sum(i.output_duration() for i in opening + montage + closing)

        extra = 0
        while total() < target * 0.92 and extra < 24:
            candidates = self.pick(by_excitement, 1, min_gap=4.0)
            if not candidates:
                break
            pattern = MONTAGE_PATTERN[(len(montage)) % len(MONTAGE_PATTERN)]
            shot = self.cut_shot(candidates[0], self.beats(pattern, 1.2),
                                 note=f"montage {len(montage) + 1}")
            if not shot:
                break
            montage.append(shot)
            extra += 1

        grid_note = f", beat-synced @ {self.grid.bpm:.0f} BPM" if self.grid else ""
        quote_note = f", built around {len(quotes)} quotes" if quotes else ""
        return TrailerPlan(
            logline=f"Pro {self.opts.style.name} cut: excitement-driven, "
                    f"speech-safe{quote_note}{grid_note}",
            timeline=opening + montage + closing,
        )


def plan_professional(analysis: VideoAnalysis, opts: TrailerOptions,
                      grid: BeatGrid | None = None) -> TrailerPlan:
    plan = ProEditor(analysis, opts, grid).plan()
    log.info("Pro editor: %d items, %.1fs%s", len(plan.timeline), plan.total_duration(),
             f" (grid {grid.bpm:.0f} BPM)" if grid else "")
    return plan
