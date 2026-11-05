"""Choosing and ordering songs. Plain functions, no I/O, easy to test.

The logic is deliberately simple (plan.md §3.8: weather is a supporting
signal, not the whole system). Songs whose `mood` suits the current weather
come first, marked WEATHER_MATCH; every other song follows in the order the
Catalogue returned it, marked GENERAL.
"""

from recommendation_service.models import Recommendation, Song, Weather

WEATHER_MATCH = "WEATHER_MATCH"
GENERAL = "GENERAL"

# Which song moods suit which weather. A song without a mood never matches.
# Two vocabularies are accepted: the labels a user can pick on upload (calm,
# mellow, upbeat, energetic) and the labels the Catalogue derives on its own
# (chill, melancholy, romantic, focus, ambient, energetic).
MOODS_FOR_WEATHER: dict[str, frozenset[str]] = {
    "RAIN": frozenset({"mellow", "calm", "chill", "melancholy"}),
    "STORM": frozenset({"mellow", "calm", "chill", "melancholy"}),
    "CLOUDY": frozenset({"mellow", "chill", "focus"}),
    "FOG": frozenset({"calm", "chill", "ambient", "romantic"}),
    "SNOW": frozenset({"calm", "chill", "ambient", "romantic"}),
    "CLEAR": frozenset({"upbeat", "energetic"}),
    "OTHER": frozenset(),
}


def rank(songs: list[Song], weather: Weather | None, limit: int) -> list[Recommendation]:
    """At most `limit` recommendations, best match first."""
    suits = MOODS_FOR_WEATHER.get(weather.condition, frozenset()) if weather else frozenset()

    def suited(song: Song) -> bool:
        return song.mood is not None and song.mood.strip().lower() in suits

    matching = [Recommendation(song, WEATHER_MATCH) for song in songs if suited(song)]
    others = [Recommendation(song, GENERAL) for song in songs if not suited(song)]
    return (matching + others)[:limit]
