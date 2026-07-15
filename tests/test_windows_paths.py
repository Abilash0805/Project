"""Regression tests for Windows filter-graph path handling.

ffmpeg's filter graph and concat demuxer treat ':' and '\\' as syntax, so
absolute Windows paths (C:\\Users\\...\\file) embedded in a filter string or a
concat list get corrupted. These tests pin the fixes: bare filenames + cwd for
graph outputs, and colon-escaping for font paths.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import shutil

from trailer_agent import videostats
from trailer_agent import render as render_mod
from trailer_agent.config import STYLES, TrailerOptions
from trailer_agent.storyboard import TimelineItem


def test_analyze_video_keeps_paths_out_of_filter_graph():
    captured: dict = {}

    def fake_run(args, *, timeout=None, cwd=None, **kw):
        captured["args"] = args
        captured["cwd"] = cwd
        # emulate ffmpeg writing its outputs into the working directory
        open(os.path.join(cwd, "cuts.txt"), "w").close()
        open(os.path.join(cwd, "motion.txt"), "w").close()
        with open(os.path.join(cwd, "sigs.gray"), "wb") as f:
            f.write(b"")

    with patch.object(videostats, "run_ffmpeg", side_effect=fake_run):
        videostats.analyze_video("/some/dir/video.mp4")

    graph = captured["args"][captured["args"].index("-filter_complex") + 1]
    # outputs referenced by bare name...
    assert "metadata=print:file=cuts.txt" in graph
    assert "file=motion.txt" in graph
    # ...and the absolute temp-dir path never leaks into the graph
    assert "trailer_vstats" not in graph
    assert os.sep + "cuts.txt" not in graph
    # ffmpeg is run from the temp dir so the bare names resolve there
    assert captured["cwd"] is not None
    assert os.path.isdir(captured["cwd"]) is False  # cleaned up in finally


def test_analyze_video_absolutizes_input():
    """The -i input is absolutized so it still resolves after the cwd change."""
    captured: dict = {}

    def fake_run(args, *, timeout=None, cwd=None, **kw):
        captured["args"] = args
        open(os.path.join(cwd, "cuts.txt"), "w").close()
        open(os.path.join(cwd, "motion.txt"), "w").close()
        with open(os.path.join(cwd, "sigs.gray"), "wb") as f:
            f.write(b"")

    with patch.object(videostats, "run_ffmpeg", side_effect=fake_run):
        videostats.analyze_video("relative/video.mp4")

    i_arg = captured["args"][captured["args"].index("-i") + 1]
    assert os.path.isabs(i_arg)


def test_title_card_uses_bare_font_name_and_cwd():
    """drawtext must reference the font by bare filename (copied into workdir)
    and run with cwd=workdir — never an absolute C:\\... path in the graph."""
    captured: dict = {}

    def fake_run(args, *, timeout=None, cwd=None, **kw):
        captured["args"] = args
        captured["cwd"] = cwd

    item = TimelineItem(kind="title", text="THE END", duration=2.5)
    with patch.object(render_mod, "run_ffmpeg", side_effect=fake_run):
        render_mod.render_card_segment(
            item, TrailerOptions(style=STYLES["epic"]),
            "/tmp/wd/seg_000.mp4", "/tmp/wd", "titlefont.ttf",
        )

    vf = captured["args"][captured["args"].index("-vf") + 1]
    assert "fontfile=titlefont.ttf:" in vf
    assert ":\\" not in vf and "C:" not in vf  # no drive-letter path leaked
    assert captured["cwd"] == "/tmp/wd"


def test_render_copies_font_into_workdir(tmp_path, monkeypatch):
    """render() copies the chosen font into the temp dir under a bare name."""
    fake_font = tmp_path / "SomeFont.ttf"
    fake_font.write_bytes(b"\x00FONT")
    copied: dict = {}

    monkeypatch.setattr(render_mod, "find_font", lambda: str(fake_font))

    def fake_card(item, opts, out_path, workdir, font_name):
        copied["font_name"] = font_name
        copied["exists"] = os.path.exists(os.path.join(workdir, font_name))
        open(out_path, "w").close()

    def fake_shot(*a, **k):
        open(a[4], "w").close()  # out_path

    monkeypatch.setattr(render_mod, "render_card_segment", fake_card)
    monkeypatch.setattr(render_mod, "render_shot_segment", fake_shot)
    monkeypatch.setattr(render_mod, "run_ffmpeg", lambda *a, **k: "")
    monkeypatch.setattr(render_mod, "_final_pass", lambda *a, **k: None)

    from trailer_agent.probe import MediaInfo
    from trailer_agent.storyboard import TrailerPlan

    plan = TrailerPlan(timeline=[TimelineItem(kind="title", text="HI", duration=2.0)])
    info = MediaInfo(path="v.mp4", duration=100.0, width=1920, height=1080,
                     fps=30.0, has_audio=True)
    render_mod.render(plan, info, TrailerOptions(), str(tmp_path / "out.mp4"))

    assert copied["font_name"] == "titlefont.ttf"  # bare name, extension preserved
    assert copied["exists"] is True
