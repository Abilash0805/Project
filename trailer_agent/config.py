"""Trailer options and visual styles."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-4-8"


@dataclass
class Style:
    name: str
    description: str          # given to the editorial brain
    grade: str                # ffmpeg video filter fragment for the look
    letterbox: bool = True    # crop to 2.39:1 cinematic bars
    card_font_size: int = 72
    card_fade: float = 0.4


STYLES: dict[str, Style] = {
    "epic": Style(
        name="epic",
        description=(
            "Sweeping, dramatic blockbuster trailer. Slow powerful opening, rising "
            "tension, accelerating montage, a beat of silence before the title, "
            "then a final button shot."
        ),
        grade="eq=contrast=1.08:saturation=1.12:brightness=-0.02,unsharp=5:5:0.4",
    ),
    "action": Style(
        name="action",
        description=(
            "Fast, punchy, high-octane. Short shots, hard cuts, peaks of energy, "
            "quick title stingers, relentless pacing that keeps accelerating."
        ),
        grade="eq=contrast=1.12:saturation=1.18,unsharp=5:5:0.6",
    ),
    "emotional": Style(
        name="emotional",
        description=(
            "Intimate and human. Longer lingering shots, gentle pacing, quiet "
            "moments given room to breathe, dialogue-forward, soft ending."
        ),
        grade="eq=contrast=1.04:saturation=0.92:brightness=0.01",
    ),
    "minimal": Style(
        name="minimal",
        description=(
            "Restrained and modern. Few carefully chosen shots, generous negative "
            "space, sparse title cards, confident silence."
        ),
        grade="eq=contrast=1.05:saturation=0.85",
        card_font_size=56,
    ),
}


@dataclass
class TrailerOptions:
    target_duration: float = 60.0
    style: Style = field(default_factory=lambda: STYLES["epic"])
    title: str = ""
    tagline: str = ""
    music: str = ""            # optional path to a music track
    use_ai: bool = True
    model: str = DEFAULT_MODEL
    output_height: int = 1080
    keep_temp: bool = False
