"""Quote mining: find the trailer-worthy lines a professional editor would build around.

Real trailers are structured around dialogue — short, punchy, high-stakes lines.
This scores every transcribed line on the qualities pros look for and picks a
spread of the best ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .transcript import SpeechSegment

# words that signal stakes, emotion, or intrigue — the vocabulary of trailers
POWER_WORDS = {
    "never", "always", "nothing", "everything", "everyone", "no one",
    "time", "run", "stop", "go", "fight", "die", "dead", "live", "alive",
    "truth", "lie", "believe", "home", "family", "afraid", "fear", "ready",
    "begin", "beginning", "end", "over", "change", "world", "last", "first",
    "only", "now", "must", "can't", "cant", "won't", "wont", "impossible",
    "chance", "risk", "trust", "remember", "forget", "promise", "secret",
    "real", "war", "love", "lost", "找", "save", "destroy", "power", "choice",
}

FILLER_WORDS = {"um", "uh", "erm", "hmm", "like", "so", "well", "okay", "yeah", "right"}

_WORD_RE = re.compile(r"[a-zA-Z']+")


def score_line(text: str) -> float:
    """How much does this line sound like it belongs in a trailer?"""
    stripped = text.strip()
    if not stripped:
        return 0.0
    words = [w.lower() for w in _WORD_RE.findall(stripped)]
    n = len(words)
    if n == 0:
        return 0.0

    score = 0.0
    # sweet spot: short, complete thoughts
    if 3 <= n <= 12:
        score += 2.0
    elif n <= 2:
        score += 0.6
    else:
        score -= (n - 12) * 0.15

    # punchy endings
    if stripped.endswith(("!", "?")):
        score += 1.2
    elif stripped.endswith(("...", "…")):
        score += 0.4
    elif stripped.endswith((".",)):
        score += 0.3  # at least a complete sentence

    # stakes vocabulary
    power = sum(1 for w in words if w in POWER_WORDS)
    score += min(power, 3) * 0.8

    # filler drags a line down
    filler = sum(1 for w in words if w in FILLER_WORDS)
    score -= filler * 0.6

    return score


@dataclass
class Quote:
    segment: SpeechSegment
    score: float

    @property
    def start(self) -> float:
        return self.segment.start

    @property
    def end(self) -> float:
        return self.segment.end

    @property
    def text(self) -> str:
        return self.segment.text


def mine_quotes(
    segments: list[SpeechSegment],
    count: int,
    *,
    min_gap: float = 20.0,
    min_score: float = 1.5,
    max_duration: float = 6.0,
) -> list[Quote]:
    """Pick the `count` best trailer lines, spread across the source.

    Returned in descending score order; callers re-sort chronologically as needed.
    """
    scored = [
        Quote(segment=s, score=score_line(s.text))
        for s in segments
        if 0.4 <= (s.end - s.start) <= max_duration
    ]
    scored.sort(key=lambda q: q.score, reverse=True)

    picked: list[Quote] = []
    for quote in scored:
        if quote.score < min_score:
            break
        if any(abs(quote.start - p.start) < min_gap for p in picked):
            continue
        picked.append(quote)
        if len(picked) >= count:
            break
    return picked
