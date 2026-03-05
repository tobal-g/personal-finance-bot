"""asyncpg connection pool lifecycle."""

import logging

import asyncpg

logger = logging.getLogger(__name__)


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool."""
    pool = await asyncpg.create_pool(
        database_url,
        min_size=2,
        max_size=10,
    )
    logger.info("db.pool_created | min_size=2 max_size=10")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    """Gracefully close the connection pool."""
    await pool.close()
    logger.info("db.pool_closed")
