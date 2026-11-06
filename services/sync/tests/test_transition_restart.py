import time
from pathlib import Path
from uuid import uuid4

import pytest

from sync_service.manager import SessionManager
from sync_service.models import (
    PlaybackState,
    ReadinessDecision,
    StartSessionRequest,
)
from sync_service.repository import SessionRepository


class Connected:
    async def send_json(self, _frame: dict[str, object]) -> None:
        return None


@pytest.mark.anyio
async def test_committed_transition_and_continue_suppression_survive_restart(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'restart.db').as_posix()}"
    manager = SessionManager(SessionRepository(database_url))
    await manager.initialize()
    owner_id, recovering_id = uuid4(), uuid4()
    request = StartSessionRequest(
        request_id=uuid4(),
        jam_id=uuid4(),
        queue_item_id=uuid4(),
        song_id=uuid4(),
        owner_id=owner_id,
        participant_ids=[owner_id, recovering_id],
    )
    now_ms = time.time_ns() // 1_000_000
    session = await manager.start(request, now_ms + 5_000, duration_ms=20_000)
    session.state = PlaybackState.PLAYING
    session.anchor_server_time_ms = now_ms - 1_000
    session.participants[owner_id].connection = Connected()  # type: ignore[assignment]
    session.participants[recovering_id].connection = Connected()  # type: ignore[assignment]
    await manager.prepare_next(
        session,
        queue_item_id=uuid4(),
        song_id=uuid4(),
        stream_url="/api/streaming/tracks/next/audio",
        duration_ms=30_000,
        prepare_deadline_ms=now_ms - 1,
    )
    session.participants[owner_id].pending_ready = True
    ready, unready, required = manager.readiness_status(session, now_ms)
    assert ready == [owner_id]
    assert unready == [recovering_id]
    assert required is True

    _, scheduled = await manager.apply_readiness_decision(
        session=session,
        request_id=uuid4(),
        decision=ReadinessDecision.CONTINUE,
        now_ms=now_ms,
        prepare_timeout_ms=8_000,
        start_lead_time_ms=500,
    )
    assert scheduled is True
    assert recovering_id in session.ignored_participant_ids
    assert session.pending is not None
    transition_ms = session.pending.transition_server_time_ms
    assert transition_ms is not None
    next_queue_item_id = session.pending.queue_item_id
    await manager.close()

    restarted = SessionManager(SessionRepository(database_url))
    await restarted.initialize()
    restored = restarted.get(request.jam_id)
    assert restored is not None
    assert restored.pending is not None
    assert restored.pending.queue_item_id == next_queue_item_id
    assert restored.pending.transition_server_time_ms == transition_ms
    assert restored.ignored_participant_ids == {recovering_id}
    await restarted.close()


@pytest.mark.anyio
async def test_wait_holds_at_boundary_then_recovery_starts_next_from_zero(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'wait.db').as_posix()}"
    manager = SessionManager(SessionRepository(database_url))
    await manager.initialize()
    owner_id, recovering_id = uuid4(), uuid4()
    request = StartSessionRequest(
        request_id=uuid4(),
        jam_id=uuid4(),
        queue_item_id=uuid4(),
        song_id=uuid4(),
        owner_id=owner_id,
        participant_ids=[owner_id, recovering_id],
    )
    now_ms = time.time_ns() // 1_000_000
    session = await manager.start(request, now_ms + 1_000, duration_ms=5_000)
    session.state = PlaybackState.PLAYING
    session.anchor_server_time_ms = now_ms - 5_000
    session.participants[owner_id].connection = Connected()  # type: ignore[assignment]
    session.participants[recovering_id].connection = Connected()  # type: ignore[assignment]
    await manager.prepare_next(
        session,
        queue_item_id=uuid4(),
        song_id=uuid4(),
        stream_url="/api/streaming/tracks/next/audio",
        duration_ms=30_000,
        prepare_deadline_ms=now_ms - 1,
    )
    assert await manager.mark_pending_ready(session, owner_id) is None

    await manager.mark_playing_if_due(session, now_ms)
    assert session.state is PlaybackState.PAUSED
    assert session.anchor_position_ms == session.duration_ms
    assert session.pending is not None
    assert session.pending.transition_server_time_ms is None

    session.ignored_participant_ids.add(recovering_id)
    future_target = now_ms + 500
    target = await manager.mark_pending_ready(
        session,
        recovering_id,
        target_server_time_ms=future_target,
    )
    assert target == future_target
    assert recovering_id not in session.ignored_participant_ids
    assert session.pending.transition_server_time_ms == future_target

    await manager.mark_playing_if_due(session, future_target)
    assert session.state is PlaybackState.PLAYING
    assert session.generation == 2
    assert session.anchor_position_ms == 0
    await manager.close()
