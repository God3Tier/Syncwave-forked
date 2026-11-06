"""Idempotently backfill hashes while preserving later legacy duplicate rows."""

import asyncio
import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from upload_service.config import Settings
from upload_service.db import Database, Status, UploadRecord, now
from upload_service.storage import S3Storage

logger = logging.getLogger(__name__)


async def backfill_hashes(
    sessions: async_sessionmaker[AsyncSession], storage: S3Storage
) -> tuple[int, int]:
    """Return (canonical hashes stored, legacy duplicates preserved)."""
    async with sessions() as session:
        rows = (
            await session.scalars(
                select(UploadRecord)
                .where(
                    UploadRecord.status == Status.PUBLISHED,
                    UploadRecord.content_sha256.is_(None),
                )
                .order_by(UploadRecord.created_at, UploadRecord.song_id)
            )
        ).all()

    stored = duplicates = 0
    for row in rows:
        digest = await asyncio.to_thread(storage.content_sha256, row.audio_reference)
        try:
            async with sessions.begin() as session:
                result = await session.execute(
                    update(UploadRecord)
                    .where(
                        UploadRecord.song_id == row.song_id,
                        UploadRecord.content_sha256.is_(None),
                    )
                    .values(content_sha256=digest, updated_at=now())
                )
                stored += result.rowcount
        except IntegrityError:
            # An older row (or a concurrent backfill) already owns this hash.
            duplicates += 1
            logger.info("upload_hash_backfill_legacy_duplicate song_id=%s", row.song_id)
    return stored, duplicates


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    database = Database(settings.database_url)
    storage = S3Storage(settings)
    try:
        stored, duplicates = await backfill_hashes(database.sessions, storage)
        logger.info(
            "upload_hash_backfill_complete stored=%d legacy_duplicates=%d",
            stored,
            duplicates,
        )
    finally:
        storage.close()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
