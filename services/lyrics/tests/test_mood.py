from lyrics_service.shared.mood import categorize_mood


def test_lyrics_use_cosine_similarity() -> None:
    lines = [{"text": "electric rhythm, we dance and feel alive"}]
    assert categorize_mood(lines, title="A sad title") == "energetic"


def test_title_is_used_when_lyrics_are_absent() -> None:
    assert categorize_mood([], title="Quiet Ocean Dream") == "chill"


def test_low_similarity_leaves_catalogue_fallback_untouched() -> None:
    assert categorize_mood([], title="Untitled Number Seven") is None


def test_low_similarity_lyrics_do_not_use_the_title() -> None:
    assert categorize_mood([{"text": "words without a mood signal"}], title="Love Forever") is None
