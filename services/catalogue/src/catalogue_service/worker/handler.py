"""Processes Catalogue events: song creation from SongUploaded, and
lyrics/waveform processing results (plan.md §2, §6, §16).

Every delivery ends in exactly one of:
  ack                      processed (duplicate deliveries are idempotent)
  reject(requeue=False)    transient failure: back in 10 s via the retry queue
  dead-letter + ack        gave up: message moved to <queue>.dlq
"""

import logging

from aio_pika.abc import AbstractIncomingMessage

from catalogue_service.shared.db import (
    CatalogueRepository,
    ProcessingStatus,
    StageStatus,
)
from catalogue_service.shared.errors import PermanentError, TransientError
from catalogue_service.shared.events import (
    FAILED_EVENT,
    MAX_ATTEMPTS,
    PROCESSED_EVENT,
    QUEUE_SONG_UPLOADED,
    SONG_READY_EVENT,
    SONG_READY_ROUTING_KEY,
    WAVEFORM_FAILED_EVENT,
    WAVEFORM_PROCESSED_EVENT,
    InvalidEvent,
    ProcessingEvent,
    Publisher,
    SongUploaded,
    build_event,
    parse_processing_event,
    parse_song_uploaded,
    previous_failures,
)

logger = logging.getLogger(__name__)


class CatalogueHandler:
    def __init__(
        self,
        repository: CatalogueRepository,
        publisher: Publisher,
        *,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._max_attempts = max_attempts

    async def __call__(self, message: AbstractIncomingMessage, queue_name: str) -> None:
        """Consumer callback. Never raises, so no message is left unacknowledged."""
        attempt = previous_failures(message.headers, queue_name) + 1
        try:
            await self._handle(message, queue_name, attempt)
        except PermanentError as exc:
            logger.error(
                "permanent failure, dead-lettering message %s from %s: %s",
                message.message_id,
                queue_name,
                exc,
            )
            await self._give_up(message, queue_name)
            return
        except Exception as exc:
            if attempt < self._max_attempts:
                logger.warning(
                    "failed, retrying in 10 s: message=%s queue=%s error=%s",
                    message.message_id,
                    queue_name,
                    _describe(exc),
                )
                await message.reject(requeue=False)
                return
            else:
                logger.error(
                    "giving up after %d attempt(s), dead-lettering message %s from %s: %s",
                    self._max_attempts,
                    message.message_id,
                    queue_name,
                    _describe(exc),
                )
                await self._give_up(message, queue_name)
                return
        await message.ack()

    async def _handle(
        self, message: AbstractIncomingMessage, queue_name: str, attempt: int
    ) -> None:
        if queue_name == QUEUE_SONG_UPLOADED:
            try:
                event = parse_song_uploaded(message.body)
            except InvalidEvent as exc:
                raise PermanentError("INVALID_EVENT", str(exc)) from exc
            await self._handle_song_uploaded(event)
        else:
            try:
                processing_event = parse_processing_event(message.body)
            except InvalidEvent as exc:
                raise PermanentError("INVALID_EVENT", str(exc)) from exc
            await self._handle_processing_result(processing_event)

    async def _handle_song_uploaded(self, event: SongUploaded) -> None:
        """Creates the initial Song record. Idempotent: the first write wins."""
        await self._repository.create_song(
            event.song_id,
            event.title,
            event.artist,
            event.audio_reference,
            event.lyrics_reference,
            event.duration_ms,
            event.event_id,
            mood=event.mood,
        )
        logger.info(
            "song created: song_id=%s title=%r artist=%r event_id=%s",
            event.song_id,
            event.title,
            event.artist,
            event.event_id,
        )

    async def _handle_processing_result(self, event: ProcessingEvent) -> None:
        """Updates one processing stage, derives readiness, and publishes
        SongReady when the song first becomes fully READY."""
        record = await self._repository.get(event.song_id)
        if record is None:
            # The SongUploaded creation event may still be in flight.
            raise TransientError(
                "SONG_NOT_FOUND", f"song {event.song_id} not yet known to Catalogue"
            )

        if event.event_type == PROCESSED_EVENT:
            if record.lyrics_status != StageStatus.READY:
                await self._repository.set_lyrics_status(
                    event.song_id, StageStatus.READY, event.event_id
                )
        elif event.event_type == FAILED_EVENT:
            if record.lyrics_status != StageStatus.READY:
                await self._repository.set_lyrics_status(
                    event.song_id, StageStatus.FAILED, event.event_id
                )
        elif event.event_type == WAVEFORM_PROCESSED_EVENT:
            duration_ms = event.payload.get("duration_ms")
            if record.waveform_status != StageStatus.READY:
                await self._repository.set_waveform_status(
                    event.song_id, StageStatus.READY, event.event_id, duration_ms
                )
        elif event.event_type == WAVEFORM_FAILED_EVENT:
            if record.waveform_status != StageStatus.READY:
                await self._repository.set_waveform_status(
                    event.song_id, StageStatus.FAILED, event.event_id
                )

        final = await self._repository.get(event.song_id)
        if final is not None and final.processing_status == ProcessingStatus.READY:
            # Re-announce when already READY too: repairs a crash between
            # committing READY and publishing SongReady (idempotent).
            await self._announce_ready(event.song_id, event.correlation_id)

    async def _announce_ready(self, song_id, correlation_id: str | None) -> None:
        event = build_event(
            SONG_READY_EVENT,
            song_id,
            {"song_id": str(song_id)},
            correlation_id=correlation_id,
        )
        await self._publisher.publish_event(event, SONG_READY_ROUTING_KEY)
        logger.info("song ready: song_id=%s", song_id)

    async def _give_up(self, message: AbstractIncomingMessage, queue_name: str) -> None:
        await self._publisher.dead_letter(message, queue_name)
        await message.ack()


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
