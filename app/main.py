"""FastAPI entrypoint with outbox relay lifecycle."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes.payments import health_router
from app.api.routes.payments import router as payments_router
from app.config import Settings, get_settings
from app.infrastructure.messaging import broker, setup_rabbitmq_topology
from app.infrastructure.outbox_relay import relay
from app.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create configured FastAPI application instance."""

    app_settings = settings or get_settings()
    configure_logging(logging.DEBUG if app_settings.debug else logging.INFO)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Startup/shutdown hooks for broker topology and relay loop."""

        broker_started = False
        if app_settings.enable_broker_startup:
            await broker.connect()
            broker_started = True
            await setup_rabbitmq_topology()
            if app_settings.enable_outbox_relay:
                relay.start()

        try:
            yield
        finally:
            if app_settings.enable_outbox_relay:
                try:
                    await relay.stop()
                except Exception:
                    logging.getLogger(__name__).exception("Failed to stop outbox relay cleanly")
            if broker_started:
                try:
                    await broker.close()
                except Exception:
                    logging.getLogger(__name__).exception("Failed to close broker cleanly")

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.include_router(health_router)
    app.include_router(payments_router)
    register_error_handlers(app)
    return app


app = create_app()


def run() -> None:
    """CLI entrypoint to run HTTP API server."""

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
