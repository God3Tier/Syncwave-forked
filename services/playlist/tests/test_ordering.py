import uuid

import pytest

from playlist_service import ordering
from playlist_service.errors import InvalidRequest, SongAlreadyInPlaylist, SongNotInPlaylist


def ids(count: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(count)]


def test_add_appends_by_default() -> None:
    a, b, c = ids(3)
    assert ordering.add_song([a, b], c) == [a, b, c]


def test_add_at_a_position_moves_later_songs_down() -> None:
    a, b, c = ids(3)
    assert ordering.add_song([a, b], c, 1) == [a, c, b]
    assert ordering.add_song([a, b], c, 0) == [c, a, b]


def test_add_at_the_end_position_is_allowed() -> None:
    a, b, c = ids(3)
    assert ordering.add_song([a, b], c, 2) == [a, b, c]


def test_add_past_the_end_is_rejected() -> None:
    a, b, c = ids(3)
    with pytest.raises(InvalidRequest):
        ordering.add_song([a, b], c, 3)


def test_add_a_duplicate_is_rejected() -> None:
    a, b = ids(2)
    with pytest.raises(SongAlreadyInPlaylist):
        ordering.add_song([a, b], a)


def test_add_does_not_change_the_input() -> None:
    a, b = ids(2)
    order = [a]
    ordering.add_song(order, b)
    assert order == [a]


def test_remove_closes_the_gap() -> None:
    a, b, c = ids(3)
    assert ordering.remove_song([a, b, c], b) == [a, c]


def test_remove_a_missing_song_is_rejected() -> None:
    a, b = ids(2)
    with pytest.raises(SongNotInPlaylist):
        ordering.remove_song([a], b)


def test_reorder_accepts_a_permutation() -> None:
    a, b, c = ids(3)
    assert ordering.reorder([a, b, c], [c, a, b]) == [c, a, b]


def test_reorder_cannot_drop_a_song() -> None:
    a, b, c = ids(3)
    with pytest.raises(InvalidRequest):
        ordering.reorder([a, b, c], [a, b])


def test_reorder_cannot_add_a_song() -> None:
    a, b, c = ids(3)
    with pytest.raises(InvalidRequest):
        ordering.reorder([a, b], [a, b, c])


def test_reorder_rejects_repeats() -> None:
    a, b = ids(2)
    with pytest.raises(InvalidRequest):
        ordering.reorder([a, b], [a, a])


def test_shuffle_keeps_the_same_songs() -> None:
    order = ids(10)
    assert sorted(ordering.shuffled(order)) == sorted(order)


def test_shuffle_always_changes_the_order_of_two_or_more_songs() -> None:
    order = ids(2)
    for _ in range(50):
        assert ordering.shuffled(order) != order


def test_shuffle_of_zero_or_one_song_is_unchanged() -> None:
    (a,) = ids(1)
    assert ordering.shuffled([]) == []
    assert ordering.shuffled([a]) == [a]


def test_shuffle_does_not_change_the_input() -> None:
    order = ids(5)
    original = list(order)
    ordering.shuffled(order)
    assert order == original
