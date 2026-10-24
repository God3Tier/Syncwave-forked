"""Validate files, store media, then commit the event for asynchronous delivery."""

import asyncio
import logging
import uuid
from pathlib import PurePath
from typing import Any, BinaryIO, Protocol

from fastapi import UploadFile
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from upload_service.config import Settings
from upload_service.db import Status, UploadRecord, now

logger = logging.getLogger(__name__)
AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
}


class UploadError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Storage(Protocol):
    def put(self, key: str, file: BinaryIO, content_type: str) -> None: ...
    def delete(self, key: str) -> None: ...


def validate_file(file: UploadFile, limit: int, *, lyrics: bool = False) -> str:
    extension = PurePath(file.filename or "").suffix.lower()
    if extension not in ({".lrc"} if lyrics else AUDIO_TYPES):
        raise UploadError(415, "UNSUPPORTED_FILE_TYPE", "Use MP3, WAV, FLAC, OGG, M4A or LRC")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0:
        raise UploadError(400, "EMPTY_FILE", "Uploaded files must not be empty")
    if size > limit:
        raise UploadError(413, "FILE_TOO_LARGE", f"The file exceeds the {limit} byte limit")
    if lyrics:
        try:
            file.file.read().decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadError(400, "INVALID_LYRICS_ENCODING", "Lyrics must be UTF-8") from exc
    else:
        header = file.file.read(64)
        signatures = {
            ".wav": header[:4] == b"RIFF" and header[8:12] == b"WAVE",
            ".flac": header.startswith(b"fLaC"),
            ".ogg": header.startswith(b"OggS"),
            ".m4a": header[4:8] == b"ftyp",
            ".mp3": header.startswith(b"ID3")
            or (len(header) > 1 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0),
        }
        if not signatures[extension]:
            raise UploadError(415, "INVALID_AUDIO", "Audio header does not match the file type")
    file.file.seek(0)
    return extension


def build_event(record: UploadRecord) -> dict[str, Any]:
    event_id = str(record.event_id)
    return {
        "event_id": event_id,
        "event_type": "SongUploaded",
        "version": 1,
        "song_id": str(record.song_id),
        "timestamp": now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "producer": "upload",
        "correlation_id": event_id,
        "payload": {
            "title": record.title,
            "artist": record.artist,
            "duration_ms": record.duration_ms,
            "audio_reference": record.audio_reference,
            "lyrics_reference": record.lyrics_reference,
        },
    }


class UploadService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], storage: Storage, settings: Settings
    ) -> None:
        self.sessions, self.storage, self.settings = sessions, storage, settings

    async def create(
        self,
        title: str,
        artist: str,
        duration_ms: int | None,
        audio: UploadFile,
        lyrics: UploadFile | None,
    ) -> UploadRecord:
        title, artist = title.strip(), artist.strip()
        if (
            not title
            or not artist
            or len(title) > 200
            or len(artist) > 200
            or "\x00" in title
            or "\x00" in artist
        ):
            raise UploadError(400, "INVALID_REQUEST", "Title and artist need 1 to 200 characters")
        extension = await asyncio.to_thread(validate_file, audio, self.settings.audio_max_bytes)
        if lyrics is not None:
            await asyncio.to_thread(
                validate_file, lyrics, self.settings.lyrics_max_bytes, lyrics=True
            )
        song_id = uuid.uuid4()
        record = UploadRecord(
            song_id=song_id,
            event_id=uuid.uuid4(),
            title=title,
            artist=artist,
            duration_ms=duration_ms,
            audio_reference=f"audio/{song_id}{extension}",
            lyrics_reference=f"lyrics/{song_id}.lrc" if lyrics else None,
            status=Status.UPLOADING,
        )
        async with self.sessions.begin() as session:
            session.add(record)

        attempted_keys = []
        try:
            attempted_keys.append(record.audio_reference)
            await asyncio.to_thread(
                self.storage.put, record.audio_reference, audio.file, AUDIO_TYPES[extension]
            )
            if lyrics is not None:
                attempted_keys.append(record.lyrics_reference)
                await asyncio.to_thread(
                    self.storage.put,
                    record.lyrics_reference,
                    lyrics.file,
                    "text/plain; charset=utf-8",
                )
        except Exception as exc:
            # S3 may have written an object even if the client saw a timeout.
            for key in attempted_keys:
                try:
                    await asyncio.to_thread(self.storage.delete, key)
                except Exception:
                    logger.warning("upload_cleanup_failed song_id=%s", song_id)
            async with self.sessions.begin() as session:
                await session.execute(
                    update(UploadRecord)
                    .where(UploadRecord.song_id == song_id)
                    .values(
                        status=Status.FAILED,
                        last_error_code="STORAGE_UNAVAILABLE",
                        updated_at=now(),
                    )
                )
            logger.warning("upload_storage_failed song_id=%s", song_id)
            raise UploadError(
                503, "STORAGE_UNAVAILABLE", f"Media could not be stored; upload ID: {song_id}"
            ) from exc

        # If this commit fails, retain the media: an ambiguous commit must never
        # delete objects that a committed event might already reference.
        async with self.sessions.begin() as session:
            await session.execute(
                update(UploadRecord)
                .where(UploadRecord.song_id == song_id)
                .values(status=Status.PENDING, event=build_event(record), updated_at=now())
            )
        logger.info("upload_accepted song_id=%s event_id=%s", song_id, record.event_id)
        async with self.sessions() as session:
            return await session.get(UploadRecord, song_id)
