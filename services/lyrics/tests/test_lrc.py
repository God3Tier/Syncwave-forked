import pytest

from lyrics_service.shared.errors import PermanentError
from lyrics_service.shared.lrc import LyricLine, parse


def lines(text: str) -> list[tuple[int, str]]:
    return [(line.time_ms, line.text) for line in parse(text.encode())]


def error_code(raw: bytes) -> str:
    with pytest.raises(PermanentError) as caught:
        parse(raw)
    return caught.value.code


def test_parses_time_tags_with_any_fraction_precision() -> None:
    assert lines("[00:01]a\n[00:02.5]b\n[00:03.25]c\n[00:04.125]d\n[01:02:50]e") == [
        (1000, "a"),
        (2500, "b"),
        (3250, "c"),
        (4125, "d"),
        (62500, "e"),
    ]


def test_ignores_id_tags_and_untimed_lines() -> None:
    text = "[ti:Song]\n[ar:Artist]\n[by:someone]\nnot timed\n\n[00:05.00]Only line\n"
    assert lines(text) == [(5000, "Only line")]


def test_several_time_tags_share_one_line_and_result_is_sorted() -> None:
    text = "[00:30.00][00:10.00]Chorus\n[00:20.00] [00:40.00]Verse\n"
    assert lines(text) == [(10000, "Chorus"), (20000, "Verse"), (30000, "Chorus"), (40000, "Verse")]


def test_sort_is_stable_for_equal_times() -> None:
    assert lines("[00:01.00]first\n[00:01.00]second") == [(1000, "first"), (1000, "second")]


def test_keeps_empty_lines_as_instrumental_breaks() -> None:
    assert lines("[00:01.00]Sing\n[00:05.00]\n") == [(1000, "Sing"), (5000, "")]


def test_applies_offset_and_clamps_at_zero() -> None:
    assert lines("[offset:+500]\n[00:00.20]a\n[00:02.00]b") == [(0, "a"), (1500, "b")]
    assert lines("[offset:-250]\n[00:01.00]a") == [(1250, "a")]


def test_strips_word_level_tags_and_keeps_bracketed_text() -> None:
    assert lines("[00:01.00]<00:01.00>Hel <00:01.50>lo\n[00:02.00][Chorus] la") == [
        (1000, "Hel lo"),
        (2000, "[Chorus] la"),
    ]


def test_accepts_utf8_with_bom_and_crlf() -> None:
    raw = "﻿[00:01.00]Café\r\n[00:02.00]日本語\r\n".encode()
    assert parse(raw) == [LyricLine(1000, "Café"), LyricLine(2000, "日本語")]


def test_rejects_invalid_seconds() -> None:
    with pytest.raises(PermanentError, match=r"line 2: invalid time tag \[01:75.00\]"):
        parse(b"[00:01.00]ok\n[01:75.00]bad")


def test_rejects_malformed_time_tag() -> None:
    assert error_code(b"[00:1x.00]bad") == "LYRICS_INVALID"


def test_rejects_invalid_offset() -> None:
    assert error_code(b"[offset:soon]\n[00:01.00]a") == "LYRICS_INVALID"


def test_rejects_lyrics_without_time_tags() -> None:
    assert error_code(b"Just some words\nwithout timing\n") == "LYRICS_NOT_TIMESTAMPED"
    assert error_code(b"") == "LYRICS_NOT_TIMESTAMPED"


def test_rejects_non_utf8() -> None:
    assert error_code("[00:01.00]Café".encode("latin-1")) == "LYRICS_INVALID_ENCODING"
