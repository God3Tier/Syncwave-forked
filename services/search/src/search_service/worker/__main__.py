"""Worker process: consumes search.song-ready.

python -m search_service.worker
"""

import asyncio
import logging
import signal

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import AMQPConnectionError

from search_service.config import Settings, configure_logging, get_settings
from search_service.shared.catalogue_client import CatalogueClient
from search_service.shared.db import Database, SearchRepository
from search_service.shared.events import DLX_EXCHANGE, QUEUE_SONG_READY, DeadLetterPublisher
from search_service.worker.handler import SearchHandler
from search_service.worker.rebuild import rebuild_index

logger = logging.getLogger("search_service.worker")

CONNECT_ATTEMPTS = 30
CONNECT_RETRY_DELAY_S = 2


async def connect(settings: Settings) -> AbstractRobustConnection:
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


async def rebuild_at_startup(catalogue: CatalogueClient, repository: SearchRepository) -> None:
    """Catches up on songs that became READY while this worker was not running."""
    try:
        count = await rebuild_index(catalogue, repository)
    except Exception as exc:
        # Not fatal: SongReady events still index new songs. Restarting the
        # worker, or running search_service.worker.rebuild, tries again.
        logger.warning("startup rebuild of the search index failed: %s", exc)
    else:
        logger.info("startup rebuild indexed %d ready song(s)", count)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    database = Database(settings.database_url)
    connection = await connect(settings)
    try:
        channel = await connection.channel(publisher_confirms=True)
        await channel.set_qos(prefetch_count=settings.amqp_prefetch)
        dlx = await channel.get_exchange(DLX_EXCHANGE)
        publisher = DeadLetterPublisher(dlx)
        catalogue_client = CatalogueClient(settings.catalogue_url)
        repository = SearchRepository(database.sessions)
        handler = SearchHandler(repository, publisher, catalogue_client)
        queue = await channel.get_queue(QUEUE_SONG_READY)
        await queue.consume(lambda message: handler(message, QUEUE_SONG_READY))
        logger.info("consuming %s with prefetch %d", QUEUE_SONG_READY, settings.amqp_prefetch)
        rebuild = asyncio.create_task(rebuild_at_startup(catalogue_client, repository))
        await stop.wait()
        rebuild.cancel()
        logger.info("stopping; unacknowledged messages return to the queue")
    finally:
        await connection.close()
        await database.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
