"""Shared pytest fixtures for unit and integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base


@pytest.fixture()
def test_settings() -> Settings:
    """Provide deterministic test settings independent of .env."""

    return Settings(
        environment="test",
        debug=False,
        api_key="test-api-key",
        database_url="sqlite+aiosqlite:///:memory:",
        rabbitmq_url="amqp://guest:guest@localhost:5672/",
        enable_broker_startup=False,
        enable_outbox_relay=False,
        gateway_sleep_min_seconds=0.01,
        gateway_sleep_max_seconds=0.02,
        webhook_retry_base_delay_seconds=0.01,
        consumer_retry_base_delay_seconds=0.01,
    )


@pytest.fixture()
async def db_session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Create isolated in-memory DB and yield async session factory."""

    db_file = tmp_path / "test.db"
    database_url = f"sqlite+aiosqlite:///{db_file.as_posix()}"

    engine = create_async_engine(database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    yield factory

    await engine.dispose()


@pytest.fixture()
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield DB session for tests."""

    async with db_session_factory() as session:
        yield session
