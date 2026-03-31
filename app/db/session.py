"""Async SQLAlchemy session factory and engine wiring."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
)

SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def init_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Build a dedicated session factory for custom database URL."""

    custom_engine = create_async_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
    )
    return async_sessionmaker(
        bind=custom_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session."""

    async with SessionFactory() as session:
        yield session
