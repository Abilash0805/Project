"""Thin wrappers around the ffmpeg / ffprobe binaries."""

from __future__ import annotations

import shutil
import subprocess


class FFmpegError(RuntimeError):
    pass


def _find(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise FFmpegError(
            f"'{binary}' not found on PATH. Install ffmpeg (e.g. `apt install ffmpeg` "
            "or `brew install ffmpeg`) and try again."
        )
    return path


# ffmpeg/ffprobe always emit UTF-8, but Python's text-mode subprocess decodes
# with locale.getpreferredencoding() by default — on Windows that's usually a
# legacy codepage (e.g. cp1252), which crashes on any non-ASCII byte (accented
# filenames, unicode metadata, non-Latin scripts). Force UTF-8 explicitly and
# never let a decode error crash the pipeline over log/metadata text.
_TEXT_KWARGS = {"encoding": "utf-8", "errors": "replace"}


def run_ffmpeg(
    args: list[str],
    *,
    capture: bool = False,
    timeout: int | None = None,
    cwd: str | None = None,
) -> str:
    """Run ffmpeg with -hide_banner -y and the given args. Returns stderr+stdout text.

    `cwd` runs ffmpeg from that directory — used so filter-graph outputs can be
    referenced by bare filename, avoiding Windows path characters (drive-letter
    ':' and '\\') that ffmpeg's filter parser would otherwise misinterpret.
    """
    cmd = [_find("ffmpeg"), "-hide_banner", "-y", *args]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if not capture else subprocess.PIPE,
        timeout=timeout,
        cwd=cwd,
        **_TEXT_KWARGS,
    )
    if proc.returncode != 0:
        output = (proc.stdout or "") + (proc.stderr or "")
        raise FFmpegError(f"ffmpeg failed ({proc.returncode}):\n{output[-4000:]}")
    if capture:
        return proc.stdout or ""
    return proc.stdout or ""


def run_ffprobe(args: list[str], *, timeout: int | None = 120) -> str:
    cmd = [_find("ffprobe"), "-hide_banner", *args]
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, **_TEXT_KWARGS
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed ({proc.returncode}):\n{proc.stderr[-4000:]}")
    return proc.stdout
