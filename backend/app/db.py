import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .models import Base

log = logging.getLogger(__name__)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine, attempts: int = 30) -> None:
    """Create tables, waiting for Postgres to accept connections."""
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            return
        except OSError as exc:
            if attempt == attempts:
                raise
            log.info("Waiting for database (%s)...", exc)
            await asyncio.sleep(2)
