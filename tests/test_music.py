"""Tests for beat detection (pure Python, no ffmpeg)."""

from trailer_agent.music import BeatGrid, detect_grid, onset_envelope


def synthetic_envelope(bpm: float, duration: float, hop: float = 0.05,
                       offset: float = 0.0):
    """Energy envelope with a spike on every beat."""
    interval = 60.0 / bpm
    n = int(duration / hop)
    times = [i * hop for i in range(n)]
    values = []
    for t in times:
        phase = (t - offset) % interval
        values.append(1.0 if phase < hop else 0.05)
    return times, values


def test_detects_120_bpm():
    times, values = synthetic_envelope(bpm=120.0, duration=30.0)
    grid = detect_grid(times, values)
    assert grid is not None
    assert abs(grid.bpm - 120.0) < 6.0


def test_detects_phase_offset():
    times, values = synthetic_envelope(bpm=100.0, duration=30.0, offset=0.25)
    grid = detect_grid(times, values)
    assert grid is not None
    # first beat should land near the 0.25s offset (modulo one interval)
    assert min(abs(grid.first_beat - 0.25), abs(grid.first_beat - 0.25 + grid.interval),
               abs(grid.first_beat - 0.25 - grid.interval)) < 0.11


def test_rejects_non_rhythmic_audio():
    # constant energy: no onsets, no beat
    times = [i * 0.05 for i in range(600)]
    values = [0.5] * 600
    assert detect_grid(times, values) is None


def test_quantize_rounds_to_beats():
    grid = BeatGrid(bpm=120.0, interval=0.5, first_beat=0.0)
    assert grid.quantize(1.1) == 1.0   # 2.2 beats -> 2 beats
    assert grid.quantize(1.3) == 1.5   # 2.6 beats -> 3 beats
    assert grid.quantize(0.1) == 0.5   # never below 1 beat


def test_onset_envelope_is_positive_flux():
    assert onset_envelope([0.1, 0.5, 0.3, 0.9]) == [0.0, 0.4, 0.0, 0.6000000000000001]
