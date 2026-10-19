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
MOODS_FOR_WEATHER: dict[str, frozenset[str]] = {
    "RAIN": frozenset({"mellow", "calm"}),
    "STORM": frozenset({"mellow", "calm"}),
    "CLOUDY": frozenset({"mellow"}),
    "FOG": frozenset({"calm"}),
    "SNOW": frozenset({"calm"}),
    "CLEAR": frozenset({"upbeat", "energetic"}),
    "OTHER": frozenset(),
}


def rank(songs: list[Song], weather: Weather | None, limit: int) -> list[Recommendation]:
    """At most `limit` recommendations, best match first."""
    suits = MOODS_FOR_WEATHER.get(weather.condition, frozenset()) if weather else frozenset()
    matching = [Recommendation(song, WEATHER_MATCH) for song in songs if song.mood in suits]
    others = [Recommendation(song, GENERAL) for song in songs if song.mood not in suits]
    return (matching + others)[:limit]
