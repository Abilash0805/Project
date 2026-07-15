"""Regression tests for Windows filter-graph path handling.

ffmpeg's filter graph and concat demuxer treat ':' and '\\' as syntax, so
absolute Windows paths (C:\\Users\\...\\file) embedded in a filter string or a
concat list get corrupted. These tests pin the fixes: bare filenames + cwd for
graph outputs, and colon-escaping for font paths.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from trailer_agent import videostats
from trailer_agent.render import escape_filter_path


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


def test_escape_filter_path_windows_font():
    # backslash form (raw Windows path)
    assert escape_filter_path(r"C:\Windows\Fonts\arial.ttf") == "C\\:/Windows/Fonts/arial.ttf"
    # forward-slash form (as stored in FONT_CANDIDATES)
    assert escape_filter_path("C:/Windows/Fonts/arialbd.ttf") == "C\\:/Windows/Fonts/arialbd.ttf"


def test_escape_filter_path_posix_is_noop():
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    assert escape_filter_path(p) == p
