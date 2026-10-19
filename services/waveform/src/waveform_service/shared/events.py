"""AMQP events in and out of the Waveform Service (contracts/events/).

The topology (exchanges, queues, retry queues, DLQs) is owned by
infrastructure/rabbitmq/definitions.json: this service only looks it up and
never declares it.
"""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import aio_pika
from aio_pika.abc import AbstractExchange, AbstractIncomingMessage

EVENTS_EXCHANGE = "syncwave.events"
DLX_EXCHANGE = "syncwave.dlx"
QUEUE = "waveform.song-uploaded"
PRODUCER = "waveform"
# Give up on the 3rd failed attempt (contracts/events/README.md)
MAX_ATTEMPTS = 3

PROCESSED_EVENT = "WaveformProcessed"
PROCESSED_ROUTING_KEY = "waveform.processed"
FAILED_EVENT = "WaveformProcessingFailed"
FAILED_ROUTING_KEY = "waveform.failed"


class InvalidEvent(Exception):
    """The message is not a usable SongUploaded event: a permanent failure.

    Carries whatever IDs could be read, so the failure can still be reported.
    """

    def __init__(
        self, message: str, *, song_id: uuid.UUID | None = None, event_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.song_id = song_id
        self.event_id = event_id


@dataclass(frozen=True, slots=True)
class SongUploaded:
    event_id: str
    song_id: uuid.UUID
    audio_reference: str


def parse_song_uploaded(body: bytes) -> SongUploaded:
    """Reads the fields this service needs and ignores the rest (tolerant reader)."""
    try:
        event = json.loads(body)
    except ValueError as exc:  # also covers UnicodeDecodeError
        raise InvalidEvent(f"body is not JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise InvalidEvent("body is not a JSON object")

    song_id = _uuid(event.get("song_id"))
    if song_id is None:
        raise InvalidEvent("song_id is missing or not a UUID")
    event_uuid = _uuid(event.get("event_id"))
    if event_uuid is None:
        raise InvalidEvent("event_id is missing or not a UUID", song_id=song_id)
    event_id = str(event_uuid)
    ids = {"song_id": song_id, "event_id": event_id}
    if event.get("event_type") != "SongUploaded":
        raise InvalidEvent(f"unexpected event_type {event.get('event_type')!r}", **ids)
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise InvalidEvent("payload is missing or not an object", **ids)
    reference = payload.get("audio_reference")
    if not isinstance(reference, str) or not reference:
        raise InvalidEvent("payload.audio_reference must be a non-empty string", **ids)
    return SongUploaded(event_id=event_id, song_id=song_id, audio_reference=reference)


def build_event(
    event_type: str, song_id: uuid.UUID, payload: dict[str, Any], *, correlation_id: str | None
) -> dict[str, Any]:
    """A new event in the shared envelope (contracts/events/envelope.schema.json)."""
    event: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "version": 1,
        "song_id": str(song_id),
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "producer": PRODUCER,
        "payload": payload,
    }
    if correlation_id is not None:
        event["correlation_id"] = correlation_id
    return event


def previous_failures(headers: Mapping[str, Any] | None, queue: str) -> int:
    """How many times processing has already failed: the count in RabbitMQ's
    x-death entry for this queue with reason "rejected" (0 on the first delivery)."""
    for death in (headers or {}).get("x-death") or []:
        if not isinstance(death, Mapping):
            continue
        if _text(death.get("queue")) == queue and _text(death.get("reason")) == "rejected":
            return int(death.get("count") or 0)
    return 0


class Publisher(Protocol):
    async def publish_event(self, event: dict[str, Any], routing_key: str) -> None: ...

    async def dead_letter(self, message: AbstractIncomingMessage, queue: str) -> None: ...


class AmqpPublisher:
    """Publishes on a channel opened with publisher confirms, so each publish
    returns only once the broker has taken responsibility for the message."""

    def __init__(self, events: AbstractExchange, dlx: AbstractExchange) -> None:
        self._events = events
        self._dlx = dlx

    async def publish_event(self, event: dict[str, Any], routing_key: str) -> None:
        message = aio_pika.Message(
            json.dumps(event).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=event["event_id"],
            type=event["event_type"],
            correlation_id=event.get("correlation_id"),
            app_id=PRODUCER,
        )
        await self._events.publish(message, routing_key=routing_key)

    async def dead_letter(self, message: AbstractIncomingMessage, queue: str) -> None:
        """Moves the original message, unchanged, to <queue>.dlq."""
        copy = aio_pika.Message(
            message.body,
            headers=dict(message.headers or {}),
            content_type=message.content_type,
            content_encoding=message.content_encoding,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            correlation_id=message.correlation_id,
            message_id=message.message_id,
            timestamp=message.timestamp,
            type=message.type,
            app_id=message.app_id,
        )
        await self._dlx.publish(copy, routing_key=queue)


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _text(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value
