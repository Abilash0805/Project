"""Tests for ffmpeg output parsing (no ffmpeg binary required)."""

from trailer_agent.audio import EnergyCurve, parse_astats_output
from trailer_agent.scenes import build_scenes, parse_scene_output

SCENE_OUTPUT = """\
frame:0    pts:12800   pts_time:4.267
lavfi.scene_score=0.412
frame:1    pts:36000   pts_time:12.0
lavfi.scene_score=0.951
frame:2    pts:90000   pts_time:30.0
lavfi.scene_score=0.33
"""

ASTATS_OUTPUT = """\
frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-40.5
frame:1    pts:24000   pts_time:0.5
lavfi.astats.Overall.RMS_level=-20.0
frame:2    pts:48000   pts_time:1
lavfi.astats.Overall.RMS_level=-inf
frame:3    pts:72000   pts_time:1.5
lavfi.astats.Overall.RMS_level=-10.0
"""


def test_parse_scene_output():
    cuts = parse_scene_output(SCENE_OUTPUT)
    assert [c.time for c in cuts] == [4.267, 12.0, 30.0]
    assert cuts[1].score == 0.951


def test_build_scenes_covers_full_duration():
    cuts = parse_scene_output(SCENE_OUTPUT)
    scenes = build_scenes(cuts, duration=60.0)
    assert scenes[0].start == 0.0
    assert scenes[-1].end == 60.0
    for a, b in zip(scenes, scenes[1:]):
        assert abs(a.end - b.start) < 1e-6  # contiguous


def test_build_scenes_splits_long_scenes():
    scenes = build_scenes([], duration=120.0, max_len=25.0)
    assert all(s.duration <= 25.0 + 1e-6 for s in scenes)
    assert abs(sum(s.duration for s in scenes) - 120.0) < 1e-6


def test_build_scenes_merges_slivers():
    from trailer_agent.scenes import Cut

    cuts = [Cut(time=10.0, score=0.5), Cut(time=10.4, score=0.6), Cut(time=20.0, score=0.4)]
    scenes = build_scenes(cuts, duration=40.0, min_len=1.2)
    assert all(s.duration >= 1.2 for s in scenes)


def test_parse_astats_handles_inf():
    points = parse_astats_output(ASTATS_OUTPUT)
    assert len(points) == 4
    assert points[2].rms_db == -70.0  # -inf clamped to silence floor


def test_energy_curve_normalization():
    curve = EnergyCurve(parse_astats_output(ASTATS_OUTPUT))
    # loudest window (-10 dB) normalizes to 1.0, quietest (-inf -> -70) to 0.0
    assert curve.peak(0.0, 2.0) == 1.0
    assert curve.mean(1.0, 1.4) == 0.0
    assert 0.0 <= curve.mean(0.0, 2.0) <= 1.0
