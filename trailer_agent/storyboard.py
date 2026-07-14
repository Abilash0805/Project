"""Trailer plan data model + validation against the source video."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MIN_SHOT = 0.6      # seconds; anything shorter reads as a glitch
MAX_TITLE = 6.0     # seconds; title cards longer than this kill momentum
SPEED_RANGE = (0.4, 3.0)


class TimelineItem(BaseModel):
    """One entry in the trailer: either a shot cut from the source, or a title card."""

    kind: Literal["shot", "title"]
    # shot fields (source timestamps in seconds)
    start: Optional[float] = None
    end: Optional[float] = None
    speed: float = 1.0
    # title fields
    text: Optional[str] = None
    duration: Optional[float] = None
    # editorial note (never rendered) — why this moment was chosen
    note: str = ""

    def output_duration(self) -> float:
        if self.kind == "title":
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
        cleaned.append(item)

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
