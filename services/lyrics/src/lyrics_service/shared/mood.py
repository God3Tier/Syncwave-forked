"""Rules-based mood categorization from parsed lyrics text.

Pure function: no I/O, deterministic. Complements title-based mood
categorization in the Catalogue Service.
"""

MOOD_KEYWORDS: dict[str, list[str]] = {
    "melancholy": ["cry", "tear", "sad", "lonely", "breakup", "blue", "alone"],
    "romantic": ["love", "heart", "kiss", "baby", "darling", "forever"],
    "energetic": ["dance", "party", "fire", "burn", "loud", "scream"],
    "chill": ["calm", "peace", "quiet", "still", "breathe", "slow", "soft"],
    "focus": ["mind", "think", "focus", "clear", "path", "way"],
}


def categorize_mood_from_lyrics(lines: list[dict]) -> str | None:
    """Derive a mood label from parsed LRC lines. Returns None when no
    mood keyword is found."""
    text = " ".join(line.get("text", "") for line in lines if line.get("text")).lower()
    if not text:
        return None
    scores = {mood: sum(1 for kw in kws if kw in text) for mood, kws in MOOD_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None
