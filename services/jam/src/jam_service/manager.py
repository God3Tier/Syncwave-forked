import asyncio
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import WebSocket

from jam_service.catalogue_client import CatalogueClient
from jam_service.guest_names import pick_guest_name
from jam_service.models import (
    AutoplayMode,
    JamLifecycle,
    JamParticipant,
    JamResponse,
    JamState,
    QueueItem,
    ReadinessDecision,
)
from jam_service.playlist_client import PlaylistClient
from jam_service.repository import JamRepository, PersistedJam
from jam_service.sync_client import (
    Command,
    ReadinessStatus,
    SyncClient,
    SyncClientError,
    SyncConflictError,
    SyncSnapshot,
)


class JamNotFoundError(LookupError):
    pass


class JamPermissionError(PermissionError):
    pass


class JamConflictError(ValueError):
    pass


AUTOPLAY_PROMPT_WINDOW_MS = 30_000
AUTOPLAY_DECISION_MS = 10_000
# If there is not enough time both to decide and to preload, use the default
# immediately so a short final track can still transition without a gap.
AUTOPLAY_IMMEDIATE_THRESHOLD_MS = 15_000
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Jam:
    jam_id: UUID
    join_code: str
    owner_id: UUID
    participant_ids: list[UUID]
    participant_usernames: dict[UUID, str]
    last_listener_active_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    queue: list[QueueItem] = field(default_factory=list)
    current_queue_item_id: UUID | None = None
    sync_generation: int | None = None
    state: JamState = JamState.IDLE
    lifecycle_state: JamLifecycle = JamLifecycle.ACTIVE
    ended_at: datetime | None = None
    autoplay_mode: AutoplayMode | None = None
    autoplay_seen_song_ids: set[UUID] = field(default_factory=set)
    autoplay_prompt_due: bool = False
    autoplay_prompt_deadline_ms: int | None = None
    autoplay_batch_number: int = 0
    autoplay_catalogue_rechecked: bool = False


class JamManager:
    def __init__(
        self,
        repository: JamRepository,
        sync: SyncClient,
        playlist: PlaylistClient,
        catalogue: CatalogueClient,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._sync = sync
        self._playlist = playlist
        self._catalogue = catalogue
        self._now = now or (lambda: datetime.now(UTC))
        self._jams: dict[UUID, Jam] = {}
        self._connections: dict[UUID, dict[WebSocket, UUID]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        for value in await self._repository.load():
            self._jams[value.jam_id] = Jam(
                jam_id=value.jam_id,
                join_code=value.join_code,
                owner_id=value.owner_id,
                participant_ids=value.participant_ids,
                participant_usernames=value.participant_usernames,
                queue=value.queue,
                current_queue_item_id=value.current_queue_item_id,
                sync_generation=value.sync_generation,
                state=value.state,
                lifecycle_state=value.lifecycle_state,
                ended_at=value.ended_at,
                last_listener_active_at=value.last_listener_active_at,
                autoplay_mode=(AutoplayMode(value.autoplay_mode) if value.autoplay_mode else None),
                autoplay_seen_song_ids=set(value.autoplay_seen_song_ids or []),
                autoplay_prompt_deadline_ms=value.autoplay_prompt_deadline_ms,
                autoplay_batch_number=value.autoplay_batch_number,
                autoplay_catalogue_rechecked=value.autoplay_catalogue_rechecked,
            )

    async def close(self) -> None:
        await self._sync.close()
        await self._playlist.close()
        await self._catalogue.close()
        await self._repository.close()

    def get(self, jam_id: UUID) -> JamResponse:
        jam = self._find(jam_id)
        return JamResponse(
            jam_id=jam.jam_id,
            join_code=jam.join_code,
            owner_id=jam.owner_id,
            participant_ids=jam.participant_ids,
            participants=[
                JamParticipant(
                    participant_id=participant_id,
                    username=jam.participant_usernames.get(
                        participant_id, f"Member {str(participant_id)[:8]}"
                    ),
                    role="OWNER" if participant_id == jam.owner_id else "MEMBER",
                )
                for participant_id in jam.participant_ids
            ],
            queue=jam.queue,
            current_queue_item_id=jam.current_queue_item_id,
            sync_generation=jam.sync_generation,
            state=jam.state,
            lifecycle_state=jam.lifecycle_state,
            member_token=None,
            autoplay_mode=jam.autoplay_mode,
            autoplay_decision_required=self._autoplay_decision_required(jam),
            autoplay_prompt_deadline_ms=jam.autoplay_prompt_deadline_ms,
            autoplay_batch_number=jam.autoplay_batch_number,
        )

    async def create(
        self, owner_id: UUID, username: str, playlist_id: UUID | None = None
    ) -> JamResponse:
        song_ids = await self._playlist.get_song_ids(playlist_id) if playlist_id else []
        async with self._lock:
            jam = Jam(
                jam_id=uuid4(),
                join_code=self._new_join_code(),
                owner_id=owner_id,
                participant_ids=[owner_id],
                participant_usernames={owner_id: username},
                last_listener_active_at=self._now(),
                queue=[
                    QueueItem(
                        queue_item_id=uuid4(),
                        song_id=song_id,
                        added_by=owner_id,
                        position=position,
                    )
                    for position, song_id in enumerate(song_ids)
                ],
            )
            self._jams[jam.jam_id] = jam
            await self._save(jam)
        return self.get(jam.jam_id)

    def find_by_code(self, join_code: str) -> UUID:
        for jam in self._jams.values():
            if jam.join_code == join_code:
                return jam.jam_id
        raise JamNotFoundError("Jam code not found")

    def _new_join_code(self) -> str:
        used = {jam.join_code for jam in self._jams.values()}
        for _ in range(20):
            code = f"{secrets.randbelow(100_000_000):08d}"
            if code not in used:
                return code
        raise JamConflictError("could not allocate a unique Jam code")

    async def refresh(self, jam_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            if jam.sync_generation is None:
                return self.get(jam_id)
            previous_generation = jam.sync_generation
            previous_current = jam.current_queue_item_id
            previous_queue_size = len(jam.queue)
            previous_autoplay = (
                jam.autoplay_mode,
                jam.autoplay_prompt_due,
                jam.autoplay_prompt_deadline_ms,
                jam.autoplay_batch_number,
                jam.autoplay_catalogue_rechecked,
            )
            snapshot = await self._sync.playback_state(jam.jam_id)
            if snapshot.queue_item_id is not None:
                jam.current_queue_item_id = snapshot.queue_item_id
            autoplay_activated = await self._refresh_autoplay(jam, snapshot)
            if jam.current_queue_item_id is not None:
                current = self._queue_item(jam, jam.current_queue_item_id)
                if (
                    current.position == len(jam.queue) - 1
                    and jam.autoplay_mode is AutoplayMode.TOP_HITS
                    and not autoplay_activated
                ):
                    await self._append_top_hits(jam)
            if snapshot.state is JamState.ENDED and jam.current_queue_item_id is not None:
                current = self._queue_item(jam, jam.current_queue_item_id)
                if current.position + 1 < len(jam.queue):
                    selection = jam.queue[current.position + 1]
                elif jam.autoplay_mode is AutoplayMode.LOOP and jam.queue:
                    selection = jam.queue[0]
                else:
                    selection = None
                if selection is not None:
                    snapshot = await self._sync.skip(
                        uuid4(), jam.jam_id, snapshot.generation, selection
                    )
                    jam.current_queue_item_id = selection.queue_item_id
            changed = (
                jam.sync_generation != snapshot.generation
                or jam.state != snapshot.state
                or previous_current != jam.current_queue_item_id
                or previous_queue_size != len(jam.queue)
                or previous_autoplay
                != (
                    jam.autoplay_mode,
                    jam.autoplay_prompt_due,
                    jam.autoplay_prompt_deadline_ms,
                    jam.autoplay_batch_number,
                    jam.autoplay_catalogue_rechecked,
                )
            )
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            await self._update_sync_queue(jam)
            if previous_generation != snapshot.generation:
                await self._record_play(jam)
            if changed:
                await self._save(jam)
        if changed:
            await self.broadcast(jam_id)
        return self.get(jam_id)

    async def join(self, jam_id: UUID, participant_id: UUID, username: str) -> JamResponse:
        async with self._lock:
            await self._add_member(jam_id, participant_id, username)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def join_guest(
        self, jam_id: UUID, participant_id: UUID, requested_name: str | None
    ) -> JamResponse:
        """Adds a guest under a readable name that no one else in the Jam uses."""
        async with self._lock:
            jam = self._find(jam_id)
            taken = (jam.participant_usernames.get(member) for member in jam.participant_ids)
            name = pick_guest_name(requested_name, (value for value in taken if value))
            await self._add_member(jam_id, participant_id, name)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def _add_member(self, jam_id: UUID, participant_id: UUID, username: str) -> None:
        """Caller holds self._lock."""
        jam = self._find(jam_id)
        self._require_active(jam)
        if participant_id not in jam.participant_ids:
            updated_participants = [*jam.participant_ids, participant_id]
            if jam.sync_generation is not None:
                await self._update_sync_participants(jam, updated_participants)
            jam.participant_ids.append(participant_id)
        jam.participant_usernames[participant_id] = username
        await self._save(jam)

    async def leave(self, jam_id: UUID, participant_id: UUID) -> None:
        ended = False
        async with self._lock:
            jam = self._find(jam_id)
            if participant_id == jam.owner_id:
                if len(jam.participant_ids) > 1:
                    raise JamConflictError("transfer ownership before leaving this Jam")
                await self._close(jam, clear_sync=True)
                ended = True
            elif participant_id not in jam.participant_ids:
                raise JamNotFoundError("member not found")
            else:
                updated_participants = [
                    value for value in jam.participant_ids if value != participant_id
                ]
                if jam.sync_generation is not None:
                    await self._update_sync_participants(jam, updated_participants)
                jam.participant_ids.remove(participant_id)
                jam.participant_usernames.pop(participant_id, None)
                await self._save(jam)
        if ended:
            await self._close_connections(jam_id, 4408, "Jam ended")
        else:
            await self._disconnect_participant(jam_id, participant_id)
            await self.broadcast(jam_id)

    async def add(self, jam_id: UUID, actor_id: UUID, song_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_active(jam)
            self._require_member(jam, actor_id)
            jam.queue.append(
                QueueItem(
                    queue_item_id=uuid4(),
                    song_id=song_id,
                    added_by=actor_id,
                    position=len(jam.queue),
                )
            )
            await self._update_sync_queue(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def remove(self, jam_id: UUID, actor_id: UUID, queue_item_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_owner(jam, actor_id)
            locked = await self._locked_queue_item_ids(jam)
            if queue_item_id in locked:
                raise JamConflictError("cannot remove the current or committed-next queue item")
            original = len(jam.queue)
            jam.queue = [item for item in jam.queue if item.queue_item_id != queue_item_id]
            if len(jam.queue) == original:
                raise JamNotFoundError("queue item not found")
            self._renumber(jam)
            await self._update_sync_queue(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def reorder(
        self, jam_id: UUID, actor_id: UUID, queue_item_ids: list[UUID]
    ) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_owner(jam, actor_id)
            if len(set(queue_item_ids)) != len(queue_item_ids):
                raise JamConflictError("queue item IDs must be unique")
            if set(queue_item_ids) != {item.queue_item_id for item in jam.queue}:
                raise JamConflictError("reorder must contain every queue item exactly once")
            locked = await self._locked_queue_item_ids(jam)
            old_positions = {item.queue_item_id: item.position for item in jam.queue}
            new_positions = {item_id: position for position, item_id in enumerate(queue_item_ids)}
            if any(old_positions[item_id] != new_positions[item_id] for item_id in locked):
                raise JamConflictError("cannot move the current or committed-next queue item")
            items = {item.queue_item_id: item for item in jam.queue}
            jam.queue = [items[item_id] for item_id in queue_item_ids]
            self._renumber(jam)
            await self._update_sync_queue(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def start(
        self, jam_id: UUID, actor_id: UUID, request_id: UUID, queue_item_id: UUID | None
    ) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_active(jam)
            self._require_owner(jam, actor_id)
            if not jam.queue:
                raise JamConflictError("queue is empty")
            selection = (
                jam.queue[0] if queue_item_id is None else self._queue_item(jam, queue_item_id)
            )
            snapshot = await self._switch_song(jam, request_id, selection)
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            jam.current_queue_item_id = selection.queue_item_id
            await self._update_sync_queue(jam)
            await self._record_play(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def command(
        self, jam_id: UUID, actor_id: UUID, request_id: UUID, command: Command
    ) -> JamResponse:
        async with self._lock:
            jam = self._active_owner(jam_id, actor_id)
            snapshot = await self._sync.command(
                command, request_id, jam.jam_id, jam.sync_generation or 0
            )
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def seek(
        self, jam_id: UUID, actor_id: UUID, request_id: UUID, position_ms: int
    ) -> JamResponse:
        async with self._lock:
            jam = self._active_owner(jam_id, actor_id)
            snapshot = await self._sync.seek(
                request_id, jam.jam_id, jam.sync_generation or 0, position_ms
            )
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def skip(self, jam_id: UUID, actor_id: UUID, request_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._active_owner(jam_id, actor_id)
            current = self._queue_item(jam, jam.current_queue_item_id)
            next_position = current.position + 1
            if next_position >= len(jam.queue):
                raise JamConflictError("there is no next queue item")
            selection = jam.queue[next_position]
            snapshot = await self._sync.skip(
                request_id, jam.jam_id, jam.sync_generation or 0, selection
            )
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            jam.current_queue_item_id = selection.queue_item_id
            await self._update_sync_queue(jam)
            await self._record_play(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def decide(
        self, jam_id: UUID, actor_id: UUID, request_id: UUID, decision: ReadinessDecision
    ) -> JamResponse:
        async with self._lock:
            jam = self._active_owner(jam_id, actor_id)
            snapshot = await self._sync.decide(
                request_id, jam.jam_id, jam.sync_generation or 0, decision
            )
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def readiness(self, jam_id: UUID, actor_id: UUID) -> ReadinessStatus:
        jam = self._active_owner(jam_id, actor_id)
        return await self._sync.readiness(jam.jam_id)

    async def set_autoplay(self, jam_id: UUID, actor_id: UUID, mode: AutoplayMode) -> JamResponse:
        async with self._lock:
            jam = self._active_owner(jam_id, actor_id)
            if jam.autoplay_mode is not None:
                return self.get(jam_id)
            jam.autoplay_mode = mode
            jam.autoplay_prompt_due = False
            jam.autoplay_prompt_deadline_ms = None
            jam.autoplay_seen_song_ids.update(item.song_id for item in jam.queue)
            if mode is AutoplayMode.TOP_HITS:
                await self._append_top_hits(jam)
                await self._update_sync_queue(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def connect(self, jam_id: UUID, participant_id: UUID, websocket: WebSocket) -> None:
        jam = self._find(jam_id)
        self._require_active(jam)
        self._require_member(jam, participant_id)
        await websocket.accept()
        self._connections.setdefault(jam_id, {})[websocket] = participant_id
        await self.touch_listener_activity(jam_id)
        await websocket.send_json(self.get(jam_id).model_dump(mode="json"))

    async def disconnect(self, jam_id: UUID, websocket: WebSocket) -> None:
        participant_id = self._connections.get(jam_id, {}).pop(websocket, None)
        if participant_id is not None:
            await self.touch_listener_activity(jam_id)

    async def touch_listener_activity(self, jam_id: UUID) -> None:
        """Record server-observed listener presence for durable inactivity expiry."""
        async with self._lock:
            jam = self._find(jam_id)
            if jam.lifecycle_state is JamLifecycle.ENDED:
                return
            active_at = self._now()
            jam.last_listener_active_at = active_at
            await self._repository.touch_listener_activity(jam_id, active_at)

    async def broadcast(self, jam_id: UUID) -> None:
        payload = self.get(jam_id).model_dump(mode="json")
        stale: list[WebSocket] = []
        for websocket in self._connections.get(jam_id, {}).copy():
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(jam_id, websocket)

    async def _disconnect_participant(self, jam_id: UUID, participant_id: UUID) -> None:
        connections = self._connections.get(jam_id, {})
        for websocket, connected_id in list(connections.items()):
            if connected_id == participant_id:
                await websocket.close(code=4403, reason="Jam membership removed")
                connections.pop(websocket, None)

    async def transfer(
        self,
        jam_id: UUID,
        actor_id: UUID,
        participant_id: UUID,
        *,
        leave: bool,
    ) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_active(jam)
            self._require_owner(jam, actor_id)
            if participant_id == actor_id or participant_id not in jam.participant_ids:
                raise JamConflictError("new owner must be another current participant")
            if leave:
                updated = [value for value in jam.participant_ids if value != actor_id]
                if jam.sync_generation is not None:
                    await self._update_sync_participants(jam, updated)
                jam.participant_ids = updated
                jam.participant_usernames.pop(actor_id, None)
            jam.owner_id = participant_id
            await self._save(jam)
        if leave:
            await self._disconnect_participant(jam_id, actor_id)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def end(self, jam_id: UUID, actor_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_owner(jam, actor_id)
            if jam.lifecycle_state is JamLifecycle.ENDED:
                return self.get(jam_id)
            await self._close(jam, clear_sync=True)
        await self.broadcast(jam_id)
        await self._close_connections(jam_id, 4408, "Jam ended")
        return self.get(jam_id)

    async def expire_inactive(self, ttl: timedelta) -> list[UUID]:
        """Close active rooms whose latest server-observed listener activity is stale."""
        expired: list[UUID] = []
        cutoff = self._now() - ttl
        async with self._lock:
            persisted_activity = await self._repository.listener_activity()
            for jam in self._jams.values():
                jam.last_listener_active_at = persisted_activity.get(
                    jam.jam_id, jam.last_listener_active_at
                )
                if (
                    jam.lifecycle_state is JamLifecycle.ACTIVE
                    and jam.last_listener_active_at <= cutoff
                ):
                    await self._close(jam, clear_sync=False)
                    expired.append(jam.jam_id)
        for jam_id in expired:
            jam = self._find(jam_id)
            if jam.sync_generation is not None:
                try:
                    await self._update_sync_participants(jam, [])
                except SyncClientError as error:
                    logger.warning(
                        "expired Jam Sync cleanup failed",
                        extra={"jam_id": str(jam_id), "error": str(error)},
                    )
            await self._close_connections(jam_id, 4408, "Jam expired after listener inactivity")
        return expired

    async def _close(self, jam: Jam, *, clear_sync: bool) -> None:
        """Mark a room ended while the caller holds the manager lock."""
        if jam.lifecycle_state is JamLifecycle.ENDED:
            return
        if clear_sync and jam.sync_generation is not None:
            await self._update_sync_participants(jam, [])
        jam.lifecycle_state = JamLifecycle.ENDED
        jam.state = JamState.ENDED
        jam.ended_at = self._now()
        await self._save(jam)

    async def _close_connections(self, jam_id: UUID, code: int, reason: str) -> None:
        for websocket in list(self._connections.get(jam_id, {})):
            try:
                await websocket.close(code=code, reason=reason)
            except Exception:
                # A peer may already have closed while the expiry sweep was persisting.
                logger.debug("Jam socket already closed", extra={"jam_id": str(jam_id)})
            finally:
                self._connections.get(jam_id, {}).pop(websocket, None)

    def _find(self, jam_id: UUID) -> Jam:
        try:
            return self._jams[jam_id]
        except KeyError as error:
            raise JamNotFoundError("Jam not found") from error

    @staticmethod
    def _require_member(jam: Jam, actor_id: UUID) -> None:
        if actor_id not in jam.participant_ids:
            raise JamPermissionError("actor is not a Jam member")

    @staticmethod
    def _require_owner(jam: Jam, actor_id: UUID) -> None:
        if actor_id != jam.owner_id:
            raise JamPermissionError("only the owner may perform this action")

    def _active_owner(self, jam_id: UUID, actor_id: UUID) -> Jam:
        jam = self._find(jam_id)
        self._require_active(jam)
        self._require_owner(jam, actor_id)
        if jam.sync_generation is None:
            raise JamConflictError("playback has not started")
        return jam

    @staticmethod
    def _require_active(jam: Jam) -> None:
        if jam.lifecycle_state is JamLifecycle.ENDED:
            raise JamConflictError("Jam has ended")

    async def _switch_song(self, jam: Jam, request_id: UUID, selection: QueueItem) -> SyncSnapshot:
        """Start `selection` for everyone.

        Once Sync has a session, every device's WebSocket belongs to it, and a
        new StartPlayback would replace it and leave those connections behind
        (no device would get PREPARE, so playback would stay PREPARING). So a
        later start moves the existing session to the new song, as a skip does.
        Sync rejects that while a song is still preparing (409). Jam's stored
        state can lag behind Sync's, so Sync makes that call.
        """
        if jam.sync_generation is not None:
            try:
                return await self._sync.skip(request_id, jam.jam_id, jam.sync_generation, selection)
            except SyncConflictError:
                raise
            except SyncClientError:
                pass  # Sync no longer has the session (it restarted); start a new one
        return await self._sync.start(
            request_id, jam.jam_id, jam.owner_id, selection, jam.participant_ids
        )

    async def _update_sync_queue(self, jam: Jam) -> None:
        if jam.sync_generation is None or jam.current_queue_item_id is None:
            return
        await self._sync.update_queue(uuid4(), jam.jam_id, jam.sync_generation, jam.queue)

    async def _update_sync_participants(self, jam: Jam, participant_ids: list[UUID]) -> None:
        """Apply membership to the current generation despite boundary races."""
        for attempt in range(3):
            snapshot = await self._sync.playback_state(jam.jam_id)
            if snapshot.queue_item_id is not None:
                jam.current_queue_item_id = snapshot.queue_item_id
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            try:
                updated = await self._sync.update_participants(
                    uuid4(), jam.jam_id, snapshot.generation, participant_ids
                )
            except SyncConflictError:
                if attempt == 2:
                    raise
                continue
            if updated.queue_item_id is not None:
                jam.current_queue_item_id = updated.queue_item_id
            self._apply_snapshot(jam, updated.generation, updated.state)
            return

    async def _locked_queue_item_ids(self, jam: Jam) -> set[UUID]:
        locked = {jam.current_queue_item_id} if jam.current_queue_item_id is not None else set()
        if jam.sync_generation is None:
            return locked
        try:
            snapshot = await self._sync.playback_state(jam.jam_id)
        except SyncClientError:
            return locked
        if snapshot.pending_queue_item_id is not None:
            locked.add(snapshot.pending_queue_item_id)
        return locked

    def _autoplay_decision_required(self, jam: Jam) -> bool:
        if jam.autoplay_mode is not None or jam.current_queue_item_id is None:
            return False
        current = self._queue_item(jam, jam.current_queue_item_id)
        return current.position == len(jam.queue) - 1 and jam.autoplay_prompt_due

    async def _refresh_autoplay(self, jam: Jam, snapshot: SyncSnapshot) -> bool:
        if jam.autoplay_mode is not None or jam.current_queue_item_id is None:
            jam.autoplay_prompt_due = False
            jam.autoplay_prompt_deadline_ms = None
            return False
        current = self._queue_item(jam, jam.current_queue_item_id)
        if current.position != len(jam.queue) - 1:
            jam.autoplay_prompt_due = False
            jam.autoplay_prompt_deadline_ms = None
            return False
        remaining_ms = self._remaining_ms(snapshot)
        if snapshot.state is not JamState.ENDED and (
            remaining_ms is None or remaining_ms > AUTOPLAY_PROMPT_WINDOW_MS
        ):
            return False
        now_ms = time.time_ns() // 1_000_000
        if jam.autoplay_prompt_deadline_ms is None:
            jam.autoplay_prompt_deadline_ms = now_ms + AUTOPLAY_DECISION_MS
        jam.autoplay_prompt_due = True
        if (
            snapshot.state is JamState.ENDED
            or (remaining_ms is not None and remaining_ms <= AUTOPLAY_IMMEDIATE_THRESHOLD_MS)
            or now_ms >= jam.autoplay_prompt_deadline_ms
        ):
            jam.autoplay_mode = AutoplayMode.TOP_HITS
            jam.autoplay_prompt_due = False
            jam.autoplay_prompt_deadline_ms = None
            jam.autoplay_seen_song_ids.update(item.song_id for item in jam.queue)
            await self._append_top_hits(jam)
            return True
        return False

    @staticmethod
    def _remaining_ms(snapshot: SyncSnapshot) -> int | None:
        if (
            snapshot.state is not JamState.PLAYING
            or snapshot.duration_ms <= 0
            or snapshot.anchor_server_time_ms is None
        ):
            return None
        now_ms = time.time_ns() // 1_000_000
        position_ms = (
            snapshot.anchor_position_ms
            + max(0, now_ms - snapshot.anchor_server_time_ms) * snapshot.playback_rate
        )
        return max(0, round(snapshot.duration_ms - position_ms))

    async def _append_top_hits(self, jam: Jam) -> None:
        excluded = {item.song_id for item in jam.queue} | jam.autoplay_seen_song_ids
        song_ids = await self._catalogue.top_songs(excluded, limit=5)
        if not song_ids:
            if jam.autoplay_catalogue_rechecked:
                jam.autoplay_mode = AutoplayMode.LOOP
            else:
                # Keep TOP_HITS for one fresh ranking pass. The next room
                # refresh is the single check for songs published meanwhile.
                jam.autoplay_catalogue_rechecked = True
            return
        jam.autoplay_catalogue_rechecked = False
        for song_id in song_ids:
            jam.queue.append(
                QueueItem(
                    queue_item_id=uuid4(),
                    song_id=song_id,
                    added_by=jam.owner_id,
                    position=len(jam.queue),
                )
            )
        jam.autoplay_seen_song_ids.update(song_ids)
        jam.autoplay_batch_number += 1

    async def _record_play(self, jam: Jam) -> None:
        if jam.sync_generation is None or jam.current_queue_item_id is None:
            return
        song_id = self._queue_item(jam, jam.current_queue_item_id).song_id
        playback_id = uuid5(NAMESPACE_URL, f"syncwave:jam:{jam.jam_id}:{jam.sync_generation}")
        try:
            await self._catalogue.record_jam_play(song_id, playback_id)
        except Exception:
            # Ranking telemetry must never interrupt playback.
            return

    @staticmethod
    def _queue_item(jam: Jam, queue_item_id: UUID | None) -> QueueItem:
        for item in jam.queue:
            if item.queue_item_id == queue_item_id:
                return item
        raise JamNotFoundError("queue item not found")

    @staticmethod
    def _renumber(jam: Jam) -> None:
        jam.queue = [
            item.model_copy(update={"position": index}) for index, item in enumerate(jam.queue)
        ]

    @staticmethod
    def _apply_snapshot(jam: Jam, generation: int, state: JamState) -> None:
        jam.sync_generation = generation
        jam.state = state

    async def _save(self, jam: Jam) -> None:
        await self._repository.save(
            PersistedJam(
                jam_id=jam.jam_id,
                join_code=jam.join_code,
                owner_id=jam.owner_id,
                state=jam.state,
                current_queue_item_id=jam.current_queue_item_id,
                sync_generation=jam.sync_generation,
                participant_ids=jam.participant_ids,
                participant_usernames=jam.participant_usernames,
                queue=jam.queue,
                lifecycle_state=jam.lifecycle_state,
                ended_at=jam.ended_at,
                last_listener_active_at=jam.last_listener_active_at,
                autoplay_mode=jam.autoplay_mode.value if jam.autoplay_mode else None,
                autoplay_seen_song_ids=list(jam.autoplay_seen_song_ids),
                autoplay_prompt_deadline_ms=jam.autoplay_prompt_deadline_ms,
                autoplay_batch_number=jam.autoplay_batch_number,
                autoplay_catalogue_rechecked=jam.autoplay_catalogue_rechecked,
            )
        )
