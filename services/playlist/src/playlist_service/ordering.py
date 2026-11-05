"""The ordering rules, as plain functions on a list of song ids.

A playlist's order is just a list; position is the index. Each function
takes the current order and returns the new one without touching the
database, so the rules can be tested on their own and the repository only
has to save the result.
"""

import random
import uuid
from collections.abc import Callable

from playlist_service.errors import InvalidRequest, SongAlreadyInPlaylist, SongNotInPlaylist

Order = list[uuid.UUID]
Shuffler = Callable[[Order], Order]


def add_song(order: Order, song_id: uuid.UUID, position: int | None = None) -> Order:
    """Appends the song, or inserts it at `position` (later songs move down)."""
    if song_id in order:
        raise SongAlreadyInPlaylist(f"Song {song_id} is already in this playlist")
    if position is None:
        return [*order, song_id]
    if position > len(order):
        raise InvalidRequest(
            f"position {position} is past the end of the playlist ({len(order)} songs)"
        )
    return [*order[:position], song_id, *order[position:]]


def remove_song(order: Order, song_id: uuid.UUID) -> Order:
    """Drops the song; later songs move up, so positions stay contiguous."""
    if song_id not in order:
        raise SongNotInPlaylist(f"Song {song_id} is not in this playlist")
    return [existing for existing in order if existing != song_id]


def reorder(order: Order, new_order: Order) -> Order:
    """Accepts `new_order` only if it holds exactly the current songs, once each,
    so a reorder can never add or drop a song."""
    if len(new_order) != len(set(new_order)):
        raise InvalidRequest("song_ids contains the same song more than once")
    if set(new_order) != set(order):
        raise InvalidRequest("song_ids must contain exactly the songs in the playlist")
    return list(new_order)


def shuffled(order: Order) -> Order:
    """A random order that differs from the current one whenever there are two
    or more songs (a shuffle that changes nothing looks broken)."""
    result = list(order)
    random.shuffle(result)
    if len(result) > 1 and result == order:
        result = [*order[1:], order[0]]
    return result
