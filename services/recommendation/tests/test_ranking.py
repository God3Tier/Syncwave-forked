from recommendation_service.models import Weather
from recommendation_service.ranking import GENERAL, WEATHER_MATCH, rank

from .conftest import song


def titles(recommendations: list) -> list[str]:
    return [item.song.title for item in recommendations]


def test_without_weather_every_song_is_general_in_catalogue_order() -> None:
    songs = [song("A", "mellow"), song("B", "upbeat"), song("C")]

    result = rank(songs, None, limit=10)

    assert titles(result) == ["A", "B", "C"]
    assert {item.reason for item in result} == {GENERAL}


def test_songs_that_suit_the_weather_come_first() -> None:
    songs = [song("Upbeat", "upbeat"), song("Mellow", "mellow"), song("Calm", "calm")]

    result = rank(songs, Weather("RAIN", 24.0), limit=10)

    assert titles(result) == ["Mellow", "Calm", "Upbeat"]
    assert [item.reason for item in result] == [WEATHER_MATCH, WEATHER_MATCH, GENERAL]


def test_the_catalogue_order_is_kept_within_each_group() -> None:
    songs = [song("M1", "mellow"), song("U1", "upbeat"), song("M2", "mellow"), song("U2", "upbeat")]

    assert titles(rank(songs, Weather("RAIN", 24.0), limit=10)) == ["M1", "M2", "U1", "U2"]


def test_clear_weather_prefers_upbeat_songs() -> None:
    songs = [song("Mellow", "mellow"), song("Upbeat", "upbeat")]

    result = rank(songs, Weather("CLEAR", 31.0), limit=10)

    assert titles(result) == ["Upbeat", "Mellow"]


def test_moods_the_catalogue_derives_also_match_the_weather() -> None:
    songs = [
        song("Romantic", "romantic"),
        song("Chill", "chill"),
        song("Melancholy", "melancholy"),
        song("Energetic", "energetic"),
    ]

    assert titles(rank(songs, Weather("RAIN", 24.0), limit=10)) == [
        "Chill",
        "Melancholy",
        "Romantic",
        "Energetic",
    ]
    assert titles(rank(songs, Weather("CLEAR", 31.0), limit=10))[0] == "Energetic"
    assert titles(rank(songs, Weather("FOG", 20.0), limit=10))[:2] == ["Romantic", "Chill"]


def test_mood_matching_ignores_case_and_spaces() -> None:
    result = rank([song("A", " Chill ")], Weather("RAIN", 24.0), limit=10)

    assert [item.reason for item in result] == [WEATHER_MATCH]


def test_songs_without_a_mood_never_match() -> None:
    result = rank([song("No mood")], Weather("RAIN", 24.0), limit=10)

    assert [item.reason for item in result] == [GENERAL]


def test_a_weather_with_no_preferred_moods_matches_nothing() -> None:
    result = rank([song("A", "mellow")], Weather("OTHER", 20.0), limit=10)

    assert [item.reason for item in result] == [GENERAL]


def test_an_unknown_condition_matches_nothing() -> None:
    result = rank([song("A", "mellow")], Weather("HURRICANE", 20.0), limit=10)

    assert [item.reason for item in result] == [GENERAL]


def test_limit_keeps_the_best_matches() -> None:
    songs = [song("U", "upbeat"), song("M1", "mellow"), song("M2", "mellow")]

    assert titles(rank(songs, Weather("RAIN", 24.0), limit=2)) == ["M1", "M2"]


def test_no_songs_gives_no_recommendations() -> None:
    assert rank([], Weather("RAIN", 24.0), limit=5) == []
