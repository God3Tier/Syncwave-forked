import uuid

import pytest

from search_service.shared.catalogue_client import SongData


@pytest.mark.anyio
async def test_indexes_song_on_ready(
    handler, repository, catalogue_client, song_ready, make_message
) -> None:
    event = song_ready(title="Demo", artist="Artist")
    catalogue_client.songs[str(event["song_id"])] = SongData(title="Demo", artist="Artist")

    message = make_message(event)
    await handler(message, "search.song-ready")

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None
    assert record.title == "Demo"
    assert record.artist == "Artist"


@pytest.mark.anyio
async def test_duplicate_delivery_is_idempotent(
    handler, repository, catalogue_client, song_ready, make_message
) -> None:
    event = song_ready()
    catalogue_client.songs[str(event["song_id"])] = SongData(title="Demo", artist="Artist")

    await handler(make_message(event), "search.song-ready")
    await handler(make_message(event), "search.song-ready")

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None


@pytest.mark.anyio
async def test_missing_song_is_permanent(handler, publisher, song_ready, make_message) -> None:
    event = song_ready()
    message = make_message(event)
    await handler(message, "search.song-ready")

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [("search.song-ready", message.body)]


@pytest.mark.anyio
async def test_invalid_event_is_dead_lettered(handler, publisher, make_message) -> None:
    message = make_message(b"not json")
    await handler(message, "search.song-ready")

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [("search.song-ready", b"not json")]


@pytest.mark.anyio
async def test_transient_failure_retries(
    handler, repository, catalogue_client, song_ready, make_message
) -> None:
    from search_service.shared.errors import TransientError

    event = song_ready()

    # catalogue client raises transient
    async def boom(_):
        raise TransientError("down")

    catalogue_client.get_song = boom  # type: ignore[assignment]

    message = make_message(event, failures=0)
    await handler(message, "search.song-ready")
    assert message.outcome == "retry"


@pytest.mark.anyio
async def test_gives_up_after_three_attempts(
    handler, publisher, catalogue_client, song_ready, make_message
) -> None:
    from search_service.shared.errors import TransientError

    event = song_ready()

    async def boom(_):
        raise TransientError("down")

    catalogue_client.get_song = boom  # type: ignore[assignment]

    message = make_message(event, failures=2)
    await handler(message, "search.song-ready")
    assert message.outcome == "ack"
    assert len(publisher.dead_lettered) == 1
