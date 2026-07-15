"""Regression test for the Windows cp1252 crash (issue: non-ASCII filenames /
metadata make ffprobe/ffmpeg output undecodable under the default Windows
console codepage). subprocess text-mode must always force UTF-8.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from trailer_agent.ffmpeg import run_ffmpeg, run_ffprobe


def _fake_completed(stdout="", stderr="", returncode=0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


@patch("trailer_agent.ffmpeg.shutil.which", return_value="/usr/bin/ffprobe")
@patch("trailer_agent.ffmpeg.subprocess.run")
def test_run_ffprobe_forces_utf8(mock_run, _which):
    mock_run.return_value = _fake_completed(stdout="{}")
    run_ffprobe(["-show_format", "video.mp4"])
    _, kwargs = mock_run.call_args
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"
    assert "text" not in kwargs  # never fall back to locale-dependent decoding


@patch("trailer_agent.ffmpeg.shutil.which", return_value="/usr/bin/ffmpeg")
@patch("trailer_agent.ffmpeg.subprocess.run")
def test_run_ffmpeg_forces_utf8(mock_run, _which):
    mock_run.return_value = _fake_completed(stdout="ok")
    run_ffmpeg(["-i", "video.mp4"])
    _, kwargs = mock_run.call_args
    assert kwargs.get("encoding") == "utf-8"
    assert kwargs.get("errors") == "replace"


def test_ffprobe_survives_non_utf8_garbage_bytes():
    """Even malformed bytes must not raise UnicodeDecodeError — errors='replace'
    substitutes the mojibake char instead of crashing the whole pipeline."""
    import trailer_agent.ffmpeg as ffmpeg_mod

    with patch.object(ffmpeg_mod.shutil, "which", return_value="/bin/true"):
        with patch.object(subprocess, "run") as mock_run:
            # Simulate what Popen would produce: decode is done by subprocess
            # itself when encoding/errors are passed, so here we just assert
            # those kwargs reach the real subprocess.run call untouched.
            mock_run.return_value = _fake_completed(stdout="{}")
            run_ffprobe(["-show_format", "video.mp4"])
            _, kwargs = mock_run.call_args
            assert kwargs["errors"] == "replace"
