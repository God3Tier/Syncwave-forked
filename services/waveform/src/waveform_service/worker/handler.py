"""Processes one SongUploaded delivery from waveform.song-uploaded (plan.md §6, §16).

Every delivery ends in exactly one of:
  ack                      processed (or already processed: duplicate delivery)
  reject(requeue=False)    transient failure: back in 10 s via waveform.song-uploaded.retry
  dead-letter + ack        gave up: message moved to waveform.song-uploaded.dlq and
                           WaveformProcessingFailed published
"""

import asyncio
import logging
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

import numpy as np
from aio_pika.abc import AbstractIncomingMessage

from waveform_service.shared.db import Status, WaveformRepository
from waveform_service.shared.errors import PermanentError, ProcessingError, TransientError
from waveform_service.shared.events import (
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
from waveform_service.shared.storage import ObjectNotFound, ObjectTooLarge
from waveform_service.shared.waveform import Bands, compute_bands, compute_peaks, duration_ms

logger = logging.getLogger(__name__)

# Decodes the audio file at a path to mono 16-bit samples at the handler's sample rate.
Decoder = Callable[[str], np.ndarray]


class AudioSource(Protocol):
    def download(self, key: str, destination: BinaryIO, max_bytes: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Waveform:
    peaks: list[float]
    duration_ms: int
    bands: Bands


class WaveformHandler:
    def __init__(
        self,
        repository: WaveformRepository,
        storage: AudioSource,
        publisher: Publisher,
        *,
        decoder: Decoder,
        sample_rate: int,
        points: int,
        frame_rate: float,
        band_count: int,
        max_bytes: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._publisher = publisher
        self._decoder = decoder
        self._sample_rate = sample_rate
        self._points = points
        self._frame_rate = frame_rate
        self._band_count = band_count
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
            await self._announce_ready(event, existing.points, existing.duration_ms or 0)
            return

        await self._repository.mark_processing(event.song_id, event.event_id)
        # Download, ffmpeg and numpy block: run them off the event loop so the
        # AMQP connection keeps answering heartbeats.
        waveform = await asyncio.to_thread(self._generate, event.audio_reference)
        await self._repository.mark_ready(
            event.song_id, waveform.peaks, waveform.duration_ms, self._sample_rate, waveform.bands
        )
        logger.info(
            "READY: %s points=%d duration_ms=%d band_frames=%d",
            context,
            len(waveform.peaks),
            waveform.duration_ms,
            waveform.bands.frame_count,
        )
        await self._announce_ready(event, len(waveform.peaks), waveform.duration_ms)

    def _generate(self, key: str) -> Waveform:
        with tempfile.TemporaryDirectory(prefix="waveform-") as directory:
            path = Path(directory) / "audio"
            try:
                with path.open("wb") as file:
                    self._storage.download(key, file, self._max_bytes)
            except ObjectNotFound as exc:
                raise TransientError("AUDIO_NOT_FOUND", str(exc)) from exc
            except ObjectTooLarge as exc:
                raise PermanentError("AUDIO_TOO_LARGE", str(exc)) from exc
            samples = self._decoder(str(path))
        return Waveform(
            peaks=compute_peaks(samples, self._points),
            duration_ms=duration_ms(samples, self._sample_rate),
            bands=compute_bands(
                samples,
                self._sample_rate,
                frame_rate=self._frame_rate,
                band_count=self._band_count,
            ),
        )

    async def _announce_ready(self, event: SongUploaded, points: int, duration: int) -> None:
        processed = build_event(
            PROCESSED_EVENT,
            event.song_id,
            {"points": points, "duration_ms": duration},
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
