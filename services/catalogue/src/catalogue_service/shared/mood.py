"""Rules-based mood categorization from song metadata.

Pure function: no I/O, no external APIs, deterministic. Easy to unit test
and easy to replace with a model later if the team wants.
"""

MOOD_KEYWORDS: dict[str, list[str]] = {
    "energetic": ["dance", "party", "gym", "workout", "upbeat", "hype"],
    "chill": ["chill", "lofi", "ambient", "relax", "study", "calm"],
    "melancholy": ["sad", "cry", "tear", "lonely", "breakup", "blue"],
    "romantic": ["love", "heart", "valentine", "kiss", "baby"],
    "focus": ["focus", "concentrate", "instrumental", "classical"],
}

DURATION_SHORT_MS = 180_000  # under 3 minutes
DURATION_LONG_MS = 300_000  # over 5 minutes


def categorize_mood(
    title: str | None,
    artist: str | None,
    duration_ms: int | None,
) -> str | None:
    """Derive a mood label from title/artist keywords, falling back to
    duration heuristics. Returns None when nothing can be inferred."""
    if not title and not artist:
        return None

    text = " ".join(filter(None, [title, artist])).lower()

    for mood, keywords in MOOD_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return mood

    if duration_ms is not None:
        if duration_ms < DURATION_SHORT_MS:
            return "energetic"
        if duration_ms > DURATION_LONG_MS:
            return "ambient"

    return None
