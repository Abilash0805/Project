"""Tests for the plan model and validation."""

from trailer_agent.storyboard import TimelineItem, TrailerPlan, validate_plan


def make_plan(items):
    return TrailerPlan(logline="test", timeline=items)


def test_output_duration_respects_speed():
    shot = TimelineItem(kind="shot", start=10.0, end=14.0, speed=2.0)
    assert shot.output_duration() == 2.0
    title = TimelineItem(kind="title", text="HELLO", duration=3.0)
    assert title.output_duration() == 3.0


def test_validate_clamps_out_of_range_timestamps():
    plan = make_plan([
        TimelineItem(kind="shot", start=-5.0, end=4.0),
        TimelineItem(kind="shot", start=95.0, end=200.0),
    ])
    validated = validate_plan(plan, source_duration=100.0, target=30.0)
    assert validated.timeline[0].start == 0.0
    assert validated.timeline[1].end == 100.0


def test_validate_drops_invalid_items():
    plan = make_plan([
        TimelineItem(kind="shot", start=None, end=None),           # missing times
        TimelineItem(kind="shot", start=10.0, end=10.1),           # too short
        TimelineItem(kind="title", text="", duration=2.0),         # empty title
        TimelineItem(kind="shot", start=5.0, end=9.0),             # valid
    ])
    validated = validate_plan(plan, source_duration=100.0, target=30.0)
    assert len(validated.timeline) == 1
    assert validated.timeline[0].start == 5.0


def test_validate_clamps_speed():
    plan = make_plan([TimelineItem(kind="shot", start=0.0, end=10.0, speed=10.0)])
    validated = validate_plan(plan, source_duration=100.0, target=30.0)
    assert validated.timeline[0].speed == 3.0


def test_validate_trims_overshoot():
    plan = make_plan([
        TimelineItem(kind="shot", start=0.0, end=40.0),
        TimelineItem(kind="shot", start=50.0, end=90.0),
    ])
    validated = validate_plan(plan, source_duration=100.0, target=30.0)
    assert validated.total_duration() <= 30.0 * 1.15 + 1e-6
    assert len(validated.timeline) >= 1
