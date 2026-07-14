"""trailer-agent: an AI agent that turns a 15-20 minute video into a cinematic trailer.

Pipeline:
  1. probe      - read duration/resolution/fps with ffprobe
  2. scenes     - detect scene cuts with ffmpeg's scene-score filter
  3. audio      - measure per-window loudness (excitement signal)
  4. transcript - optional speech-to-text (faster-whisper, if installed)
  5. brain      - Claude picks the moments and writes the trailer structure
                  (heuristic editor used as fallback when no API key is set)
  6. render     - ffmpeg cuts, paces, grades, letterboxes, adds title cards
                  and music ducking, and outputs the final trailer
"""

__version__ = "0.1.0"
