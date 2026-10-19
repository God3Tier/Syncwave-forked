"""Worker process: consumes waveform.song-uploaded.

    python -m waveform_service.worker

Runs from the same image as the API, as the `waveform-worker` service.
"""

import asyncio
import functools
import logging
import signal

import aio_pika
from aio_pika.abc import AbstractRobustConnection
from aio_pika.exceptions import AMQPConnectionError

from waveform_service.config import Settings, configure_logging, get_settings
from waveform_service.shared.db import Database, WaveformRepository
from waveform_service.shared.events import DLX_EXCHANGE, EVENTS_EXCHANGE, QUEUE, AmqpPublisher
from waveform_service.shared.storage import S3Storage
from waveform_service.shared.waveform import decode
from waveform_service.worker.handler import WaveformHandler

logger = logging.getLogger("waveform_service.worker")

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
    storage = S3Storage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.aws_region,
        force_path_style=settings.s3_force_path_style,
    )
    connection = await connect(settings)
    try:
        channel = await connection.channel(publisher_confirms=True)
        await channel.set_qos(prefetch_count=settings.amqp_prefetch)
        publisher = AmqpPublisher(
            await channel.get_exchange(EVENTS_EXCHANGE),
            await channel.get_exchange(DLX_EXCHANGE),
        )
        handler = WaveformHandler(
            WaveformRepository(database.sessions),
            storage,
            publisher,
            decoder=functools.partial(
                decode,
                sample_rate=settings.waveform_sample_rate,
                timeout_s=settings.waveform_decode_timeout_s,
            ),
            sample_rate=settings.waveform_sample_rate,
            points=settings.waveform_points,
            frame_rate=settings.waveform_frame_rate,
            band_count=settings.waveform_bands,
            max_bytes=settings.waveform_max_audio_bytes,
        )
        # Passive lookup: definitions.json owns the queue and its arguments.
        queue = await channel.get_queue(QUEUE)
        await queue.consume(handler)
        logger.info("consuming %s with prefetch %d", QUEUE, settings.amqp_prefetch)
        await stop.wait()
        logger.info("stopping; unacknowledged messages return to the queue")
    finally:
        await connection.close()
        await database.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
