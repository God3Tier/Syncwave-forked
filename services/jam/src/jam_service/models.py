from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JamState(StrEnum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    SCHEDULED = "SCHEDULED"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class QueueItem(StrictModel):
    queue_item_id: UUID
    song_id: UUID
    added_by: UUID
    position: int = Field(ge=0)


class JamResponse(StrictModel):
    jam_id: UUID
    owner_id: UUID
    participant_ids: list[UUID]
    queue: list[QueueItem]
    current_queue_item_id: UUID | None
    sync_generation: int | None
    state: JamState
    member_token: str | None = None
    member_id: UUID | None = None


class CreateJamRequest(StrictModel):
    playlist_id: UUID | None = None


class AddQueueItemRequest(StrictModel):
    song_id: UUID


class ReorderQueueRequest(StrictModel):
    queue_item_ids: list[UUID] = Field(min_length=1)


class StartPlaybackRequest(StrictModel):
    request_id: UUID
    queue_item_id: UUID | None = None


class PlaybackCommandRequest(StrictModel):
    request_id: UUID


class SeekRequest(PlaybackCommandRequest):
    position_ms: int = Field(ge=0)


class ReadinessDecision(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT = "WAIT"
    CANCEL = "CANCEL"


class ReadinessDecisionRequest(PlaybackCommandRequest):
    decision: ReadinessDecision


class ReadinessStatusResponse(StrictModel):
    generation: int
    prepare_deadline_ms: int
    timed_out: bool
    decision_required: bool
    ready_participant_ids: list[UUID]
    unready_participant_ids: list[UUID]
