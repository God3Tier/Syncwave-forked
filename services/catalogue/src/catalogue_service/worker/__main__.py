"""Worker process: consumes catalogue.song-uploaded and
catalogue.processing-results.

    python -m catalogue_service.worker

Runs from the same image as the API, as the `catalogue-worker` service.
"""

import asyncio
import logging
import signal

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import AMQPConnectionError

from catalogue_service.config import Settings, configure_logging, get_settings
from catalogue_service.shared.db import CatalogueRepository, Database
from catalogue_service.shared.events import (
    DLX_EXCHANGE,
    EVENTS_EXCHANGE,
    QUEUE_PROCESSING_RESULTS,
    QUEUE_SONG_UPLOADED,
    AmqpPublisher,
)
from catalogue_service.worker.handler import CatalogueHandler

logger = logging.getLogger("catalogue_service.worker")

CONNECT_ATTEMPTS = 30
CONNECT_RETRY_DELAY_S = 2


async def connect(settings: Settings) -> AbstractRobustConnection:
    """A robust connection reconnects by itself once established, but the
    first connection attempt has to be retried here."""
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            return await aio_pika.connect_robust(
                host=settings.amqp_host,
                port=settings.amqp_port,
                login=settings.amqp_user,
                password=settings.amqp_password,
                client_properties={"connection_name": f"{settings.service_name}-worker"},
            )
        except (OSError, AMQPConnectionError) as exc:
            if attempt == CONNECT_ATTEMPTS:
                raise
            logger.warning("RabbitMQ is not reachable (%s), retrying", exc)
            await asyncio.sleep(CONNECT_RETRY_DELAY_S)
    raise AssertionError("unreachable")


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass  # Windows: Ctrl+C raises KeyboardInterrupt instead

    database = Database(settings.database_url)
    connection = await connect(settings)
    try:
        channel = await connection.channel(publisher_confirms=True)
        await channel.set_qos(prefetch_count=settings.amqp_prefetch)
        publisher = AmqpPublisher(
            await channel.get_exchange(EVENTS_EXCHANGE),
            await channel.get_exchange(DLX_EXCHANGE),
        )
        handler = CatalogueHandler(
            CatalogueRepository(database.sessions),
            publisher,
        )
        # Passive lookup: definitions.json owns the queues and their arguments.
        queue_uploaded = await channel.get_queue(QUEUE_SONG_UPLOADED)
        await queue_uploaded.consume(lambda message: handler(message, QUEUE_SONG_UPLOADED))
        queue_results = await channel.get_queue(QUEUE_PROCESSING_RESULTS)
        await queue_results.consume(lambda message: handler(message, QUEUE_PROCESSING_RESULTS))
        logger.info(
            "consuming %s and %s with prefetch %d",
            QUEUE_SONG_UPLOADED,
            QUEUE_PROCESSING_RESULTS,
            settings.amqp_prefetch,
        )
        await stop.wait()
        logger.info("stopping; unacknowledged messages return to the queue")
    finally:
        await connection.close()
        await database.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
