"""Lightweight cosine mood classification for lyrics and song titles."""

import math
import re
from collections import Counter

MIN_COSINE_SIMILARITY = 0.20

MOOD_PROFILES: dict[str, frozenset[str]] = {
    "melancholy": frozenset(
        {
            "sad",
            "sorrow",
            "lonely",
            "alone",
            "tear",
            "cry",
            "broken",
            "goodbye",
            "loss",
            "pain",
            "blue",
            "empty",
            "darkness",
        }
    ),
    "romantic": frozenset(
        {
            "love",
            "heart",
            "kiss",
            "baby",
            "darling",
            "forever",
            "romance",
            "beloved",
            "together",
            "touch",
            "desire",
            "wedding",
        }
    ),
    "energetic": frozenset(
        {
            "dance",
            "party",
            "fire",
            "burn",
            "loud",
            "scream",
            "run",
            "racing",
            "power",
            "electric",
            "alive",
            "jump",
            "rhythm",
        }
    ),
    "chill": frozenset(
        {
            "calm",
            "peace",
            "quiet",
            "still",
            "breathe",
            "slow",
            "soft",
            "relax",
            "gentle",
            "ocean",
            "dream",
            "easy",
        }
    ),
    "focus": frozenset(
        {
            "mind",
            "think",
            "focus",
            "clear",
            "path",
            "study",
            "work",
            "concentrate",
            "learn",
            "purpose",
            "steady",
            "instrumental",
        }
    ),
}

_VOCABULARY = frozenset().union(*MOOD_PROFILES.values())


def categorize_mood(lines: list[dict], *, title: str | None = None) -> str | None:
    """Use lyrics when present, otherwise title; low confidence means no override."""
    lyrics = " ".join(str(line.get("text", "")) for line in lines if line.get("text")).strip()
    return _closest_mood(lyrics or title or "")


def _closest_mood(text: str) -> str | None:
    vector = Counter(token for token in re.findall(r"[a-z]+", text.lower()) if token in _VOCABULARY)
    if not vector:
        return None

    magnitude = math.sqrt(sum(count * count for count in vector.values()))
    scores = {
        mood: sum(vector[token] for token in profile) / (magnitude * math.sqrt(len(profile)))
        for mood, profile in MOOD_PROFILES.items()
    }
    best = max(scores, key=scores.get)
    return best if scores[best] >= MIN_COSINE_SIMILARITY else None
