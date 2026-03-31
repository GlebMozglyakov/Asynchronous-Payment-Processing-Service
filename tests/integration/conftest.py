"""Integration fixtures for API application tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base
from app.main import create_app


@pytest.fixture()
def integration_settings(tmp_path: Path) -> Settings:
    db_file = tmp_path / "integration.db"
    return Settings(
        environment="test",
        debug=False,
        api_key="integration-api-key",
        database_url=f"sqlite+aiosqlite:///{db_file.as_posix()}",
        rabbitmq_url="amqp://guest:guest@localhost:5672/",
        enable_broker_startup=False,
        enable_outbox_relay=False,
        gateway_sleep_min_seconds=0.01,
        gateway_sleep_max_seconds=0.02,
        webhook_retry_base_delay_seconds=0.01,
        consumer_retry_base_delay_seconds=0.01,
    )


@pytest.fixture()
async def integration_engine(
    integration_settings: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(integration_settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


@pytest.fixture()
async def app_client(
    integration_settings: Settings,
    integration_engine: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(integration_settings)

    async def _session_dependency() -> AsyncIterator[AsyncSession]:
        async with integration_engine() as session:
            yield session

    from app.db.session import get_db_session

    app.dependency_overrides[get_db_session] = _session_dependency

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
