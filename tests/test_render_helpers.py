"""Tests for pure renderer helpers (no ffmpeg binary required)."""

from trailer_agent.config import STYLES, TrailerOptions
from trailer_agent.render import _letterbox_filter, _shot_filters, atempo_chain, drawtext_escape
from trailer_agent.storyboard import TimelineItem


def test_atempo_chain_in_range():
    assert atempo_chain(1.5) == "atempo=1.5"
    assert atempo_chain(0.7) == "atempo=0.7"


def test_atempo_chain_slow():
    # 0.4 = 0.5 * 0.8
    assert atempo_chain(0.4) == "atempo=0.5,atempo=0.8"


def test_atempo_chain_fast():
    # 3.0 = 2.0 * 1.5
    assert atempo_chain(3.0) == "atempo=2,atempo=1.5"


def test_drawtext_escape():
    assert drawtext_escape("IT'S TIME: NOW") == "IT\\'S TIME\\: NOW"
    assert "\\," in drawtext_escape("a,b")


def test_letterbox_filter_bar_math():
    lb = _letterbox_filter(1920, 1080)
    # 1920 / 2.39 = 803 -> bars of 138px top and bottom
    assert "h=138" in lb
    assert "y=942" in lb


def test_shot_filters_include_style_grade_and_speed():
    opts = TrailerOptions(style=STYLES["action"])
    item = TimelineItem(kind="shot", start=0.0, end=4.0, speed=2.0)
    vf = _shot_filters(opts, item)
    assert "setpts=PTS/2" in vf
    assert "eq=contrast=1.12" in vf
    assert vf.endswith("format=yuv420p")


def test_shot_filters_include_fades():
    opts = TrailerOptions(style=STYLES["epic"])
    item = TimelineItem(kind="shot", start=0.0, end=4.0, fade_out=0.5)
    vf = _shot_filters(opts, item)
    assert "fade=t=out:st=3.500:d=0.500" in vf
