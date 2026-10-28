"""AMQP events in and out of the Search Service (contracts/events/).

The topology (exchanges, queues, retry queues, DLQs) is owned by
infrastructure/rabbitmq/definitions.json: this service only looks it up and
never declares it.
"""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

QUEUE_SONG_READY = "search.song-ready"
EVENTS_EXCHANGE = "syncwave.events"
DLX_EXCHANGE = "syncwave.dlx"
MAX_ATTEMPTS = 3
PRODUCER = "search"


class InvalidEvent(Exception):
    """The message is not a usable event: a permanent failure."""

    def __init__(
        self,
        message: str,
        *,
        song_id: uuid.UUID | None = None,
        event_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.song_id = song_id
        self.event_id = event_id


@dataclass(frozen=True, slots=True)
class SongReady:
    event_id: str
    song_id: uuid.UUID


def parse_song_ready(body: bytes) -> SongReady:
    """Reads the fields Search needs from a SongReady event."""
    try:
        event = json.loads(body)
    except ValueError as exc:
        raise InvalidEvent(f"body is not JSON: {exc}") from exc
    if not isinstance(event, dict):
        raise InvalidEvent("body is not a JSON object")

    if event.get("event_type") != "SongReady":
        raise InvalidEvent(f"unexpected event_type {event.get('event_type')!r}")

    event_uuid = _uuid(event.get("event_id"))
    if event_uuid is None:
        raise InvalidEvent("event_id is missing or not a UUID")
    event_id = str(event_uuid)

    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise InvalidEvent("payload is missing or not an object", event_id=event_id)

    top_level_song_id = _uuid(event.get("song_id"))
    payload_song_id = _uuid(payload.get("song_id"))
    song_id = top_level_song_id or payload_song_id
    if song_id is None:
        raise InvalidEvent("song_id is missing or not a UUID", event_id=event_id)
    if (
        top_level_song_id is not None
        and payload_song_id is not None
        and top_level_song_id != payload_song_id
    ):
        raise InvalidEvent("payload.song_id does not match song_id", event_id=event_id)

    return SongReady(event_id=event_id, song_id=song_id)


def previous_failures(headers: Mapping[str, Any] | None, queue: str) -> int:
    for death in (headers or {}).get("x-death") or []:
        if not isinstance(death, Mapping):
            continue
        if _text(death.get("queue")) == queue and _text(death.get("reason")) == "rejected":
            return int(death.get("count") or 0)
    return 0


class DeadLetterPublisher:
    """Moves a failed message, unchanged, to <queue>.dlq."""

    def __init__(self, dlx: aio_pika.abc.AbstractExchange) -> None:
        self._dlx = dlx

    async def dead_letter(self, message: AbstractIncomingMessage, queue: str) -> None:
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
