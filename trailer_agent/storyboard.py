"""Trailer plan data model + validation against the source video."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MIN_SHOT = 0.45     # seconds; allows 1-beat flash cuts at fast tempos
MAX_TITLE = 6.0     # seconds; title cards longer than this kill momentum
MAX_BLACK = 1.5     # seconds; dip-to-black gaps stay short
SPEED_RANGE = (0.4, 3.0)


class TimelineItem(BaseModel):
    """One entry in the trailer: a shot from the source, a title card, or a black gap."""

    kind: Literal["shot", "title", "black"]
    # shot fields (source timestamps in seconds)
    start: Optional[float] = None
    end: Optional[float] = None
    speed: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    # title/black fields
    text: Optional[str] = None
    duration: Optional[float] = None
    # editorial note (never rendered) — why this moment was chosen
    note: str = ""

    def output_duration(self) -> float:
        if self.kind in ("title", "black"):
            return self.duration or 2.0
        if self.start is None or self.end is None:
            return 0.0
        return max(self.end - self.start, 0.0) / max(self.speed, 0.01)


class TrailerPlan(BaseModel):
    """The editorial blueprint the renderer executes."""

    logline: str = Field(default="", description="One sentence describing the trailer's angle")
    timeline: list[TimelineItem] = Field(default_factory=list)

    def total_duration(self) -> float:
        return sum(item.output_duration() for item in self.timeline)

    def shots(self) -> list[TimelineItem]:
        return [i for i in self.timeline if i.kind == "shot"]


def validate_plan(plan: TrailerPlan, source_duration: float, target: float) -> TrailerPlan:
    """Clamp, drop, and trim until the plan is physically renderable and near target length."""
    cleaned: list[TimelineItem] = []
    for item in plan.timeline:
        if item.kind == "black":
            item.duration = min(max(item.duration or 0.3, 0.1), MAX_BLACK)
            cleaned.append(item)
            continue

        if item.kind == "title":
            if not item.text or not item.text.strip():
                continue
            item.duration = min(max(item.duration or 2.0, 0.8), MAX_TITLE)
            cleaned.append(item)
            continue

        if item.start is None or item.end is None:
            continue
        item.start = min(max(item.start, 0.0), source_duration)
        item.end = min(max(item.end, 0.0), source_duration)
        if item.end - item.start < MIN_SHOT:
            continue
        item.speed = min(max(item.speed, SPEED_RANGE[0]), SPEED_RANGE[1])
        item.fade_in = min(max(item.fade_in, 0.0), 2.0)
        item.fade_out = min(max(item.fade_out, 0.0), 2.0)
        cleaned.append(item)

    # a plan that is only cards/gaps is not a trailer
    if not any(i.kind == "shot" for i in cleaned):
        cleaned = [i for i in plan.timeline if i.kind == "shot"]

    plan = TrailerPlan(logline=plan.logline, timeline=cleaned)

    # trim overshoot: shorten the longest shots until within 15% of target
    while plan.total_duration() > target * 1.15:
        shots = plan.shots()
        if not shots:
            break
        longest = max(shots, key=lambda s: s.output_duration())
        excess = plan.total_duration() - target
        cut = min(excess * longest.speed, longest.output_duration() * longest.speed * 0.5)
        new_end = longest.end - cut  # type: ignore[operator]
        if new_end - longest.start < MIN_SHOT:  # type: ignore[operator]
            plan.timeline.remove(longest)
        else:
            longest.end = new_end
    return plan
