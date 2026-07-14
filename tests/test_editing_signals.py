"""Tests for speech-safe cutting, silence parsing, motion parsing, and dedupe."""

from trailer_agent.audio import SpeechRegion, parse_silence_output, snap_to_speech
from trailer_agent.videostats import Fingerprints, parse_motion_output

SILENCE_LOG = """\
[silencedetect @ 0x55] silence_start: 4.2
[silencedetect @ 0x55] silence_end: 6.0 | silence_duration: 1.8
[silencedetect @ 0x55] silence_start: 20.5
"""

MOTION_LOG = """\
frame:0    pts:0     pts_time:0
lavfi.signalstats.YDIF=1.25
frame:1    pts:7200  pts_time:0.2
lavfi.signalstats.YDIF=14.8
"""


def test_parse_silence_inverts_to_speech_regions():
    regions = parse_silence_output(SILENCE_LOG, duration=30.0)
    # speech: [0, 4.2], [6.0, 20.5]; trailing silence runs to the end
    assert len(regions) == 2
    assert (regions[0].start, regions[0].end) == (0.0, 4.2)
    assert (regions[1].start, regions[1].end) == (6.0, 20.5)


def test_parse_motion_output():
    points = parse_motion_output(MOTION_LOG)
    assert len(points) == 2
    assert points[1].time == 0.2
    assert points[1].rms_db == 14.8


def test_snap_extends_to_let_phrase_finish():
    speech = [SpeechRegion(start=10.0, end=13.0)]
    # cut ends at 12.2, mid-sentence; the phrase end (13.0) is within tolerance
    start, end = snap_to_speech(8.0, 12.2, speech)
    assert end == 13.0
    assert start == 8.0


def test_snap_includes_phrase_start():
    speech = [SpeechRegion(start=9.5, end=13.0)]
    # cut starts at 10.0, clipping the first word; snap back to 9.5
    start, end = snap_to_speech(10.0, 15.0, speech)
    assert start == 9.5


def test_snap_never_collapses_shot():
    speech = [SpeechRegion(start=0.0, end=100.0)]
    start, end = snap_to_speech(50.0, 52.0, speech)
    assert (start, end) == (50.0, 52.0)  # nothing sensible to snap to; unchanged


def test_fingerprint_distance():
    a = bytes([10] * 64)
    b = bytes([10] * 64)
    c = bytes([200] * 64)
    assert Fingerprints.distance(a, b) == 0.0
    assert Fingerprints.distance(a, c) == 190.0
    assert Fingerprints.distance(a, None) == 255.0


def test_fingerprints_frame_lookup():
    raw = bytes([1] * 64) + bytes([2] * 64) + bytes([3] * 64)
    fp = Fingerprints(raw)
    assert len(fp) == 3
    assert fp.at(0.5) == bytes([1] * 64)
    assert fp.at(2.9) == bytes([3] * 64)
    assert fp.at(99.0) == bytes([3] * 64)  # clamps to last frame
