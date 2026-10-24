import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import WebSocket

from jam_service.models import JamResponse, JamState, QueueItem, ReadinessDecision
from jam_service.playlist_client import PlaylistClient
from jam_service.repository import JamRepository, PersistedJam
from jam_service.sync_client import Command, ReadinessStatus, SyncClient


class JamNotFoundError(LookupError):
    pass


class JamPermissionError(PermissionError):
    pass


class JamConflictError(ValueError):
    pass


@dataclass(slots=True)
class Jam:
    jam_id: UUID
    owner_id: UUID
    participant_ids: list[UUID]
    queue: list[QueueItem] = field(default_factory=list)
    current_queue_item_id: UUID | None = None
    sync_generation: int | None = None
    state: JamState = JamState.IDLE


class JamManager:
    def __init__(
        self,
        repository: JamRepository,
        sync: SyncClient,
        playlist: PlaylistClient,
        member_token: str,
    ) -> None:
        self._repository = repository
        self._sync = sync
        self._playlist = playlist
        self._member_token = member_token
        self._jams: dict[UUID, Jam] = {}
        self._connections: dict[UUID, dict[WebSocket, UUID]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        for value in await self._repository.load():
            self._jams[value.jam_id] = Jam(
                jam_id=value.jam_id,
                owner_id=value.owner_id,
                participant_ids=value.participant_ids,
                queue=value.queue,
                current_queue_item_id=value.current_queue_item_id,
                sync_generation=value.sync_generation,
                state=value.state,
            )

    async def close(self) -> None:
        await self._sync.close()
        await self._playlist.close()
        await self._repository.close()

    def get(self, jam_id: UUID, include_token: bool = False) -> JamResponse:
        jam = self._find(jam_id)
        return JamResponse(
            jam_id=jam.jam_id,
            owner_id=jam.owner_id,
            participant_ids=jam.participant_ids,
            queue=jam.queue,
            current_queue_item_id=jam.current_queue_item_id,
            sync_generation=jam.sync_generation,
            state=jam.state,
            member_token=self._member_token if include_token else None,
        )

    async def create(self, owner_id: UUID, playlist_id: UUID | None = None) -> JamResponse:
        song_ids = await self._playlist.get_song_ids(playlist_id) if playlist_id else []
        async with self._lock:
            jam = Jam(
                jam_id=uuid4(),
                owner_id=owner_id,
                participant_ids=[owner_id],
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
        return self.get(jam.jam_id, include_token=True)

    async def refresh(self, jam_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            if jam.sync_generation is None:
                return self.get(jam_id)
            snapshot = await self._sync.playback_state(jam.jam_id)
            changed = jam.sync_generation != snapshot.generation or jam.state != snapshot.state
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            if changed:
                await self._save(jam)
        if changed:
            await self.broadcast(jam_id)
        return self.get(jam_id)

    async def join(self, jam_id: UUID, participant_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            if participant_id not in jam.participant_ids:
                updated_participants = [*jam.participant_ids, participant_id]
                if jam.sync_generation is not None:
                    await self._sync.update_participants(
                        uuid4(), jam.jam_id, jam.sync_generation, updated_participants
                    )
                jam.participant_ids.append(participant_id)
                await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id, include_token=True)

    async def leave(self, jam_id: UUID, participant_id: UUID) -> None:
        async with self._lock:
            jam = self._find(jam_id)
            if participant_id == jam.owner_id:
                raise JamConflictError("owner cannot leave an active Jam")
            if participant_id not in jam.participant_ids:
                raise JamNotFoundError("member not found")
            updated_participants = [
                value for value in jam.participant_ids if value != participant_id
            ]
            if jam.sync_generation is not None:
                await self._sync.update_participants(
                    uuid4(), jam.jam_id, jam.sync_generation, updated_participants
                )
            jam.participant_ids.remove(participant_id)
            await self._save(jam)
        await self._disconnect_participant(jam_id, participant_id)
        await self.broadcast(jam_id)

    async def add(self, jam_id: UUID, actor_id: UUID, song_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_member(jam, actor_id)
            jam.queue.append(
                QueueItem(
                    queue_item_id=uuid4(),
                    song_id=song_id,
                    added_by=actor_id,
                    position=len(jam.queue),
                )
            )
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def remove(self, jam_id: UUID, actor_id: UUID, queue_item_id: UUID) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_owner(jam, actor_id)
            if jam.current_queue_item_id == queue_item_id:
                raise JamConflictError("cannot remove the current queue item")
            original = len(jam.queue)
            jam.queue = [item for item in jam.queue if item.queue_item_id != queue_item_id]
            if len(jam.queue) == original:
                raise JamNotFoundError("queue item not found")
            self._renumber(jam)
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
            items = {item.queue_item_id: item for item in jam.queue}
            jam.queue = [items[item_id] for item_id in queue_item_ids]
            self._renumber(jam)
            await self._save(jam)
        await self.broadcast(jam_id)
        return self.get(jam_id)

    async def start(
        self, jam_id: UUID, actor_id: UUID, request_id: UUID, queue_item_id: UUID | None
    ) -> JamResponse:
        async with self._lock:
            jam = self._find(jam_id)
            self._require_owner(jam, actor_id)
            if not jam.queue:
                raise JamConflictError("queue is empty")
            selection = (
                jam.queue[0] if queue_item_id is None else self._queue_item(jam, queue_item_id)
            )
            snapshot = await self._sync.start(
                request_id, jam.jam_id, jam.owner_id, selection, jam.participant_ids
            )
            self._apply_snapshot(jam, snapshot.generation, snapshot.state)
            jam.current_queue_item_id = selection.queue_item_id
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

    async def connect(self, jam_id: UUID, participant_id: UUID, websocket: WebSocket) -> None:
        jam = self._find(jam_id)
        self._require_member(jam, participant_id)
        await websocket.accept()
        self._connections.setdefault(jam_id, {})[websocket] = participant_id
        await websocket.send_json(self.get(jam_id).model_dump(mode="json"))

    def disconnect(self, jam_id: UUID, websocket: WebSocket) -> None:
        self._connections.get(jam_id, {}).pop(websocket, None)

    async def broadcast(self, jam_id: UUID) -> None:
        payload = self.get(jam_id).model_dump(mode="json")
        stale: list[WebSocket] = []
        for websocket in self._connections.get(jam_id, {}).copy():
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(jam_id, websocket)

    async def _disconnect_participant(self, jam_id: UUID, participant_id: UUID) -> None:
        connections = self._connections.get(jam_id, {})
        for websocket, connected_id in list(connections.items()):
            if connected_id == participant_id:
                await websocket.close(code=4403, reason="Jam membership removed")
                connections.pop(websocket, None)

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
        self._require_owner(jam, actor_id)
        if jam.sync_generation is None:
            raise JamConflictError("playback has not started")
        return jam

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
                owner_id=jam.owner_id,
                state=jam.state,
                current_queue_item_id=jam.current_queue_item_id,
                sync_generation=jam.sync_generation,
                participant_ids=jam.participant_ids,
                queue=jam.queue,
            )
        )
