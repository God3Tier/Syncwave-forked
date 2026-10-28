"""Processes Search events: indexes a song when it becomes READY."""

import logging

from aio_pika.abc import AbstractIncomingMessage

from search_service.shared.catalogue_client import CatalogueClient
from search_service.shared.db import SearchRepository
from search_service.shared.errors import PermanentError
from search_service.shared.events import (
    InvalidEvent,
    parse_song_ready,
    previous_failures,
)

logger = logging.getLogger(__name__)


class SearchHandler:
    def __init__(
        self,
        repository: SearchRepository,
        dead_letter_publisher,
        catalogue_client: CatalogueClient,
        *,
        max_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._publisher = dead_letter_publisher
        self._catalogue = catalogue_client
        self._max_attempts = max_attempts

    async def __call__(self, message: AbstractIncomingMessage, queue_name: str) -> None:
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
        try:
            event = parse_song_ready(message.body)
        except InvalidEvent as exc:
            raise PermanentError("INVALID_EVENT", str(exc)) from exc

        song = await self._catalogue.get_song(event.song_id)
        await self._repository.upsert(event.song_id, song.title, song.artist)
        logger.info("indexed song: song_id=%s event_id=%s", event.song_id, event.event_id)

    async def _give_up(self, message: AbstractIncomingMessage, queue_name: str) -> None:
        await self._publisher.dead_letter(message, queue_name)
        await message.ack()


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
