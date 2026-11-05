"""Rebuilds the search index from Catalogue, the canonical source (plan.md §16,
"Search Indexing Failure": retry/rebuild search state).

The worker runs it once at startup, so songs that became READY while Search
was down, or before it existed, are indexed. Safe to repeat: rows are upserted.
To rebuild by hand:

    docker compose exec search-worker python -m search_service.worker.rebuild
"""

import asyncio
import logging

from search_service.config import configure_logging, get_settings
from search_service.shared.catalogue_client import CatalogueClient
from search_service.shared.db import Database, SearchRepository

logger = logging.getLogger(__name__)


async def rebuild_index(catalogue: CatalogueClient, repository: SearchRepository) -> int:
    """Indexes every READY song in Catalogue. Returns how many it indexed."""
    count = 0
    async for song_id, song in catalogue.ready_songs():
        await repository.upsert(song_id, song.title, song.artist)
        count += 1
    return count


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    try:
        count = await rebuild_index(
            CatalogueClient(settings.catalogue_url), SearchRepository(database.sessions)
        )
        logger.info("rebuilt search index: %d ready song(s) indexed", count)
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(run())
