"""Combine scene cuts, loudness, and transcript into one scored scene table."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from .audio import EnergyCurve, analyze_energy
from .probe import MediaInfo, probe
from .scenes import Scene, build_scenes, detect_cuts
from .transcript import SpeechSegment, transcribe

log = logging.getLogger(__name__)

MAX_TEXT_PER_SCENE = 220  # keep the brain's context compact


@dataclass
class VideoAnalysis:
    info: MediaInfo
    scenes: list[Scene]
    has_transcript: bool = False

    def to_compact_json(self) -> str:
        rows = [
            {
                "i": i,
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "dur": round(s.duration, 2),
                "energy": round(s.energy, 3),
                "peak": round(s.peak, 3),
                "cut": round(s.cut_score, 3),
                **({"text": s.text} if s.text else {}),
            }
            for i, s in enumerate(self.scenes)
        ]
        return json.dumps(
            {
                "duration": round(self.info.duration, 2),
                "resolution": f"{self.info.width}x{self.info.height}",
                "fps": round(self.info.fps, 2),
                "scenes": rows,
            },
            ensure_ascii=False,
        )


def _attach_energy(scenes: list[Scene], curve: EnergyCurve) -> None:
    for scene in scenes:
        scene.energy = curve.mean(scene.start, scene.end)
        scene.peak = curve.peak(scene.start, scene.end)


def _attach_transcript(scenes: list[Scene], segments: list[SpeechSegment]) -> None:
    for scene in scenes:
        parts: list[str] = []
        for seg in segments:
            if seg.end <= scene.start or seg.start >= scene.end:
                continue
            parts.append(seg.text)
        text = " ".join(parts).strip()
        if len(text) > MAX_TEXT_PER_SCENE:
            text = text[: MAX_TEXT_PER_SCENE - 1] + "…"
        scene.text = text


def analyze(
    path: str,
    *,
    scene_threshold: float = 0.27,
    with_transcript: bool = True,
) -> VideoAnalysis:
    info = probe(path)
    log.info("Probed %s: %.1fs %dx%d @ %.2ffps", path, info.duration, info.width,
             info.height, info.fps)

    cuts = detect_cuts(path, threshold=scene_threshold)
    scenes = build_scenes(cuts, info.duration)
    log.info("Detected %d cuts -> %d scenes", len(cuts), len(scenes))

    if info.has_audio:
        try:
            curve = analyze_energy(path)
            _attach_energy(scenes, curve)
        except Exception as exc:
            log.warning("Audio analysis failed (%s); using neutral energy", exc)
            for scene in scenes:
                scene.energy = 0.5
    else:
        for scene in scenes:
            scene.energy = 0.5

    has_transcript = False
    if with_transcript and info.has_audio:
        segments = transcribe(path)
        if segments:
            _attach_transcript(scenes, segments)
            has_transcript = True

    return VideoAnalysis(info=info, scenes=scenes, has_transcript=has_transcript)
