"""Drain committed receipts with publisher confirms and persistent messages."""

import asyncio
import json
import logging
import os
from datetime import timedelta
from typing import Any, Protocol

import aio_pika
from aio_pika.abc import AbstractExchange
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from upload_service.config import Settings, positive_int
from upload_service.db import Database, Status, UploadRecord, now

logger = logging.getLogger(__name__)


class Publisher(Protocol):
    async def publish(self, event: dict[str, Any]) -> None: ...


class AmqpPublisher:
    def __init__(self, exchange: AbstractExchange) -> None:
        self.exchange = exchange

    async def publish(self, event: dict[str, Any]) -> None:
        await self.exchange.publish(
            aio_pika.Message(
                json.dumps(event).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=event["event_id"],
                type="SongUploaded",
                correlation_id=event["correlation_id"],
                app_id="upload",
            ),
            routing_key="song.uploaded",
            mandatory=True,
            timeout=10,
        )


async def dispatch_one(sessions: async_sessionmaker[AsyncSession], publisher: Publisher) -> bool:
    async with sessions.begin() as session:
        record = await session.scalar(
            select(UploadRecord)
            .where(UploadRecord.status == Status.PENDING, UploadRecord.next_attempt_at <= now())
            .order_by(UploadRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            return False
        record.publish_attempts += 1
        try:
            async with asyncio.timeout(15):
                await publisher.publish(record.event)
        except Exception:
            record.last_error_code = "PUBLISH_RETRYING"
            record.next_attempt_at = now() + timedelta(
                seconds=min(2 ** min(record.publish_attempts, 6), 60)
            )
            logger.warning(
                "upload_publish_retry song_id=%s event_id=%s attempt=%s",
                record.song_id,
                record.event_id,
                record.publish_attempts,
            )
        else:
            record.status = Status.PUBLISHED
            record.last_error_code = None
            record.published_at = now()
            logger.info("upload_published song_id=%s event_id=%s", record.song_id, record.event_id)
        record.updated_at = now()
    return True


async def run() -> None:
    settings = Settings.from_env()
    database = Database(settings.database_url)
    try:
        while True:
            try:
                connection = await aio_pika.connect_robust(
                    host=os.getenv("AMQP_HOST", "localhost"),
                    port=positive_int("AMQP_PORT", 5672),
                    login=os.getenv("AMQP_USER", "syncwave"),
                    password=os.getenv("AMQP_PASSWORD", "syncwave"),
                    virtualhost=os.getenv("AMQP_VHOST", "/"),
                    timeout=10,
                )
                async with connection:
                    channel = await connection.channel(
                        publisher_confirms=True, on_return_raises=True
                    )
                    exchange = await channel.get_exchange("syncwave.events", ensure=True)
                    publisher = AmqpPublisher(exchange)
                    while True:
                        if not await dispatch_one(database.sessions, publisher):
                            await asyncio.sleep(settings.poll_seconds)
            except Exception:
                logger.warning("upload_publisher_unavailable; retrying")
                await asyncio.sleep(settings.poll_seconds)
    finally:
        await database.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(run())
