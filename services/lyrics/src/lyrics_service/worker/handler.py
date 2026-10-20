"""Processes one SongUploaded delivery from lyrics.song-uploaded (plan.md §6, §16).

Every delivery ends in exactly one of:
  ack                      processed (or already processed: duplicate delivery)
  reject(requeue=False)    transient failure: back in 10 s via lyrics.song-uploaded.retry
  dead-letter + ack        gave up: message moved to lyrics.song-uploaded.dlq and
                           LyricsProcessingFailed published
"""

import asyncio
import logging
import uuid
from typing import Protocol

from aio_pika.abc import AbstractIncomingMessage

from lyrics_service.shared import lrc
from lyrics_service.shared.db import LyricsRepository, Status
from lyrics_service.shared.errors import PermanentError, ProcessingError, TransientError
from lyrics_service.shared.events import (
    FAILED_EVENT,
    FAILED_ROUTING_KEY,
    MAX_ATTEMPTS,
    PROCESSED_EVENT,
    PROCESSED_ROUTING_KEY,
    QUEUE,
    InvalidEvent,
    Publisher,
    SongUploaded,
    build_event,
    parse_song_uploaded,
    previous_failures,
)
from lyrics_service.shared.storage import ObjectNotFound, ObjectTooLarge

logger = logging.getLogger(__name__)


class LyricsSource(Protocol):
    def read(self, key: str, max_bytes: int) -> bytes: ...


class LyricsHandler:
    def __init__(
        self,
        repository: LyricsRepository,
        storage: LyricsSource,
        publisher: Publisher,
        *,
        max_bytes: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._publisher = publisher
        self._max_bytes = max_bytes

    async def __call__(self, message: AbstractIncomingMessage) -> None:
        """Consumer callback. Never raises, so no message is left unacknowledged."""
        try:
            await self._handle(message)
        except Exception:
            logger.exception("unexpected error, sending message %s to retry", message.message_id)
            try:
                await message.reject(requeue=False)
            except Exception:
                logger.exception("could not reject message %s", message.message_id)

    async def _handle(self, message: AbstractIncomingMessage) -> None:
        attempt = previous_failures(message.headers, QUEUE) + 1
        try:
            event = parse_song_uploaded(message.body)
        except InvalidEvent as exc:
            error = PermanentError("INVALID_EVENT", str(exc))
            await self._give_up(message, exc.song_id, exc.event_id, error, attempt)
            return

        context = f"event_id={event.event_id} song_id={event.song_id} attempt={attempt}"
        try:
            await self._process(event, context)
        except PermanentError as exc:
            await self._give_up(message, event.song_id, event.event_id, exc, attempt)
            return
        except Exception as exc:
            if attempt < MAX_ATTEMPTS:
                logger.warning("failed, retrying in 10 s: %s error=%s", context, _describe(exc))
                await message.reject(requeue=False)
                return
            error = (
                exc
                if isinstance(exc, ProcessingError)
                else ProcessingError("PROCESSING_ERROR", _describe(exc))
            )
            await self._give_up(message, event.song_id, event.event_id, error, attempt)
            return
        await message.ack()

    async def _process(self, event: SongUploaded, context: str) -> None:
        existing = await self._repository.get(event.song_id)
        if existing is not None and existing.status == Status.READY:
            # Duplicate delivery, or a crash between committing and publishing:
            # announce the stored result again instead of redoing the work.
            logger.info("already READY, re-announcing: %s", context)
            await self._announce_ready(event, existing.line_count)
            return

        await self._repository.mark_processing(event.song_id, event.event_id)
        lines = await self._load_lines(event.lyrics_reference)
        await self._repository.mark_ready(event.song_id, lines)
        logger.info("READY: %s lines=%d", context, len(lines))
        await self._announce_ready(event, len(lines))

    async def _load_lines(self, reference: str | None) -> list[dict[str, int | str]]:
        if reference is None:
            return []  # uploaded without lyrics (instrumental)
        try:
            raw = await asyncio.to_thread(self._storage.read, reference, self._max_bytes)
        except ObjectNotFound as exc:
            raise TransientError("LYRICS_FILE_NOT_FOUND", str(exc)) from exc
        except ObjectTooLarge as exc:
            raise PermanentError("LYRICS_TOO_LARGE", str(exc)) from exc
        return [line.as_dict() for line in lrc.parse(raw)]

    async def _announce_ready(self, event: SongUploaded, line_count: int) -> None:
        processed = build_event(
            PROCESSED_EVENT,
            event.song_id,
            {"line_count": line_count},
            correlation_id=event.event_id,
        )
        await self._publisher.publish_event(processed, PROCESSED_ROUTING_KEY)

    async def _give_up(
        self,
        message: AbstractIncomingMessage,
        song_id: uuid.UUID | None,
        event_id: str | None,
        error: ProcessingError,
        attempt: int,
    ) -> None:
        logger.error(
            "giving up after %d attempt(s), moving to %s.dlq: event_id=%s song_id=%s "
            "error_code=%s error=%s",
            attempt,
            QUEUE,
            event_id,
            song_id,
            error.code,
            error.message,
        )
        recorded = song_id is not None
        if song_id is not None:
            try:
                recorded = await self._repository.mark_failed(
                    song_id, event_id, error.code, error.message
                )
            except Exception:
                logger.exception("could not record the failure for song_id=%s", song_id)
            if not recorded:
                logger.warning("song_id=%s is already READY; not reporting a failure", song_id)

        await self._publisher.dead_letter(message, QUEUE)
        if song_id is not None and recorded:
            failed = build_event(
                FAILED_EVENT,
                song_id,
                {"error_code": error.code, "message": error.message, "attempts": attempt},
                correlation_id=event_id,
            )
            await self._publisher.publish_event(failed, FAILED_ROUTING_KEY)
        await message.ack()


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
