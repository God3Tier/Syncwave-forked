import asyncio
from uuid import uuid4

from jam_service.models import JamState, QueueItem
from jam_service.repository import JamRepository, PersistedJam


def test_repository_round_trip(tmp_path) -> None:
    asyncio.run(repository_round_trip(tmp_path))


async def repository_round_trip(tmp_path) -> None:
    repository = JamRepository(f"sqlite+aiosqlite:///{(tmp_path / 'jam.db').as_posix()}")
    await repository.initialize()
    owner_id = uuid4()
    item = QueueItem(queue_item_id=uuid4(), song_id=uuid4(), added_by=owner_id, position=0)
    expected = PersistedJam(
        jam_id=uuid4(),
        join_code="12345678",
        owner_id=owner_id,
        state=JamState.PREPARING,
        current_queue_item_id=item.queue_item_id,
        sync_generation=2,
        participant_ids=[owner_id],
        participant_usernames={owner_id: "owner"},
        queue=[item],
    )
    await repository.save(expected)
    loaded = (await repository.load())[0]
    assert loaded == expected
    await repository.close()
