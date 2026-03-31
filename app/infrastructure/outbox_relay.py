"""Outbox relay loop that publishes pending outbox events to RabbitMQ."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.session import SessionFactory
from app.infrastructure.messaging import broker, payments_exchange, payments_routing_key
from app.infrastructure.repositories import OutboxRepository

logger = logging.getLogger(__name__)

settings = get_settings()


class OutboxRelay:
    """Periodic relay that guarantees eventual publication of outbox events."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
    ) -> None:
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._session_factory = session_factory

    def start(self) -> None:
        """Start background relay loop if not already running."""

        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="outbox-relay")

    async def stop(self) -> None:
        """Signal relay to stop and wait for graceful shutdown."""

        self._stop_event.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        relay_lock_id = str(uuid4())
        logger.info("Outbox relay started", extra={"lock_id": relay_lock_id})
        while not self._stop_event.is_set():
            try:
                processed = await self._publish_once(relay_lock_id)
                if not processed:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=settings.outbox_poll_interval_seconds,
                    )
            except TimeoutError:
                # polling timeout is expected while waiting for new events
                continue
            except Exception:
                logger.exception("Outbox relay iteration failed")
                await asyncio.sleep(settings.outbox_poll_interval_seconds)

        logger.info("Outbox relay stopped")

    async def _publish_once(self, relay_lock_id: str) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                outbox_repo = OutboxRepository(session)
                events = await outbox_repo.acquire_pending_batch(
                    lock_id=relay_lock_id,
                    batch_size=settings.outbox_batch_size,
                    lock_ttl_seconds=settings.outbox_lock_ttl_seconds,
                )

            if not events:
                return False

            for event in events:
                async with session.begin():
                    outbox_repo = OutboxRepository(session)
                    try:
                        event_id = (
                            event.payload.get("event_id")
                            if isinstance(event.payload, dict)
                            else None
                        )
                        correlation_id = (
                            event.payload.get("payment_id")
                            if isinstance(event.payload, dict)
                            else str(event.aggregate_id)
                        )
                        await broker.publish(
                            message=event.payload,
                            exchange=payments_exchange,
                            routing_key=payments_routing_key,
                            message_id=str(event_id or event.id),
                            correlation_id=str(correlation_id),
                            headers={"event_type": event.event_type},
                            persist=True,
                        )
                        await outbox_repo.mark_published(event_id=event.id)
                        logger.info(
                            "Outbox event published",
                            extra={
                                "event_id": str(event.id),
                                "event_type": event.event_type,
                                "aggregate_id": str(event.aggregate_id),
                            },
                        )
                    except Exception as exc:
                        await outbox_repo.mark_publish_failed(event_id=event.id, error=str(exc))
                        logger.exception(
                            "Failed to publish outbox event",
                            extra={
                                "event_id": str(event.id),
                                "aggregate_id": str(event.aggregate_id),
                            },
                        )

            return True


relay = OutboxRelay()
