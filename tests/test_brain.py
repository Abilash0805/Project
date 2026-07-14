"""Tests for the heuristic editor and plan orchestration (no API calls)."""

from trailer_agent.analysis import VideoAnalysis
from trailer_agent.brain import make_plan, plan_heuristic
from trailer_agent.config import STYLES, TrailerOptions
from trailer_agent.probe import MediaInfo
from trailer_agent.scenes import Scene


def fake_analysis(duration=900.0, n_scenes=30) -> VideoAnalysis:
    """A synthetic 15-minute video with varied energy."""
    step = duration / n_scenes
    scenes = []
    for i in range(n_scenes):
        energy = (i * 37 % 100) / 100.0  # pseudo-random but deterministic
        scenes.append(
            Scene(
                start=i * step,
                end=(i + 1) * step,
                cut_score=0.4,
                energy=energy,
                peak=min(energy + 0.2, 1.0),
            )
        )
    info = MediaInfo(path="fake.mp4", duration=duration, width=1920, height=1080,
                     fps=30.0, has_audio=True)
    return VideoAnalysis(info=info, scenes=scenes)


def opts(**kw) -> TrailerOptions:
    defaults = dict(target_duration=60.0, style=STYLES["epic"], use_ai=False,
                    title="THE TEST", tagline="Nothing is what it seems")
    defaults.update(kw)
    return TrailerOptions(**defaults)


def test_heuristic_plan_structure():
    plan = plan_heuristic(fake_analysis(), opts())
    kinds = [i.kind for i in plan.timeline]
    assert "shot" in kinds and "title" in kinds
    # hook comes first and is a shot
    assert plan.timeline[0].kind == "shot"
    # title card text is uppercased
    titles = [i for i in plan.timeline if i.kind == "title"]
    assert any(t.text == "THE TEST" for t in titles)


def test_heuristic_never_reuses_footage():
    plan = plan_heuristic(fake_analysis(), opts())
    shots = plan.shots()
    for a in shots:
        overlaps = [
            b for b in shots
            if b is not a and a.start < b.end and b.start < a.end
        ]
        assert not overlaps, f"shot {a.start}-{a.end} overlaps {overlaps}"


def test_make_plan_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    plan = make_plan(fake_analysis(), opts(use_ai=True))
    assert plan.timeline  # heuristic fallback produced a plan


def test_make_plan_duration_near_target():
    plan = make_plan(fake_analysis(), opts())
    assert plan.total_duration() <= 60.0 * 1.15
    assert plan.total_duration() >= 20.0  # sanity: not degenerate


def test_no_title_cards_when_no_title_given():
    plan = plan_heuristic(fake_analysis(), opts(title="", tagline=""))
    assert all(i.kind == "shot" for i in plan.timeline)
