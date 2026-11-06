from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaybackState(StrEnum):
    PREPARING = "PREPARING"
    SCHEDULED = "SCHEDULED"
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class ReadinessDecision(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT = "WAIT"
    CANCEL = "CANCEL"


class StartSessionRequest(StrictModel):
    request_id: UUID
    jam_id: UUID
    queue_item_id: UUID
    song_id: UUID
    owner_id: UUID
    participant_ids: list[UUID] = Field(min_length=1)


class StartSessionResponse(StrictModel):
    jam_id: UUID
    generation: int
    state: PlaybackState
    websocket_path: str
    mock_participant_token: str


class PlaybackSnapshotResponse(StrictModel):
    jam_id: UUID
    generation: int
    state: PlaybackState
    song_id: UUID
    anchor_server_time_ms: int | None
    anchor_position_ms: int
    playback_rate: float


class ReadinessStatusResponse(StrictModel):
    jam_id: UUID
    generation: int
    prepare_deadline_ms: int
    timed_out: bool
    decision_required: bool
    ready_participant_ids: list[UUID]
    unready_participant_ids: list[UUID]


class ReadinessDecisionRequest(StrictModel):
    request_id: UUID
    generation: int = Field(ge=1)
    decision: ReadinessDecision


class ReadinessDecisionResponse(StrictModel):
    jam_id: UUID
    generation: int
    state: PlaybackState
    decision: ReadinessDecision
    target_server_time_ms: int | None


class PlaybackCommandRequest(StrictModel):
    request_id: UUID
    generation: int = Field(ge=1)


class SeekPlaybackRequest(PlaybackCommandRequest):
    position_ms: int = Field(ge=0)


class SkipPlaybackRequest(PlaybackCommandRequest):
    queue_item_id: UUID
    song_id: UUID


class ClientFrame(StrictModel):
    type: str
    jam_id: UUID
    seq: int = Field(ge=0)
    sent_at_ms: int = Field(ge=0)
    payload: dict[str, Any]


class TimePingPayload(StrictModel):
    sample_id: UUID
    client_sent_ms: int = Field(ge=0)


class ReadyPayload(StrictModel):
    generation: int = Field(ge=1)
    buffered_duration_ms: int = Field(ge=0)
    media_duration_ms: int = Field(gt=0)


class NotReadyPayload(StrictModel):
    generation: int = Field(ge=1)
    reason: Literal["AUDIO_LOCKED", "AUDIO_SUSPENDED", "AUDIO_ERROR", "BUFFER_LOST"]


class PlaybackStatusPayload(StrictModel):
    generation: int = Field(ge=1)
    measured_server_time_ms: int = Field(ge=0)
    position_ms: int = Field(ge=0)
    buffering: bool
    clock_offset_ms: float | None = None
    round_trip_delay_ms: float | None = Field(default=None, ge=0)
    start_error_ms: int | None = None


class TimePingFrame(ClientFrame):
    type: Literal["TIME_PING"]
    payload: TimePingPayload


class ReadyFrame(ClientFrame):
    type: Literal["READY"]
    payload: ReadyPayload


class NotReadyFrame(ClientFrame):
    type: Literal["NOT_READY"]
    payload: NotReadyPayload


class PlaybackStatusFrame(ClientFrame):
    type: Literal["PLAYBACK_STATUS"]
    payload: PlaybackStatusPayload
