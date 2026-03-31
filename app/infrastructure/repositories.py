"""Persistence repositories for payments and outbox events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent, Payment
from app.domain.enums import Currency, OutboxStatus, PaymentStatus


class PaymentRepository:
    """CRUD helpers for payment entity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        query: Select[tuple[Payment]] = select(Payment).where(
            Payment.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        query: Select[tuple[Payment]] = select(Payment).where(Payment.id == payment_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def upsert_pending(
        self,
        *,
        amount: Decimal,
        currency: Currency,
        description: str,
        metadata: dict[str, Any],
        idempotency_key: str,
        webhook_url: str,
    ) -> tuple[Payment, bool]:
        """Create pending payment safely under race conditions.

        Uses INSERT .. ON CONFLICT to guarantee idempotency at DB level.
        Returns (payment, created_now).
        """

        values = {
            "amount": amount,
            "currency": currency,
            "description": description,
            "metadata_json": metadata,
            "status": PaymentStatus.PENDING,
            "idempotency_key": idempotency_key,
            "webhook_url": webhook_url,
        }

        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "postgresql":
            stmt = (
                pg_insert(Payment)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
                .returning(Payment)
            )
            result = await self._session.execute(stmt)
            created = result.scalar_one_or_none()
            if created is not None:
                return created, True
            existing = await self.get_by_idempotency_key(idempotency_key)
            assert existing is not None, "existing payment must be present after conflict"
            return existing, False

        elif dialect_name == "sqlite":
            stmt = (
                sqlite_insert(Payment)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[Payment.idempotency_key])
                .returning(Payment)
            )
            result = await self._session.execute(stmt)
            created = result.scalar_one_or_none()
            if created is not None:
                return created, True
            existing = await self.get_by_idempotency_key(idempotency_key)
            assert existing is not None, "existing payment must be present after conflict"
            return existing, False

        else:
            msg = f"Unsupported SQL dialect for upsert: {dialect_name}"
            raise RuntimeError(msg)

    async def mark_processed(
        self,
        *,
        payment_id: UUID,
        status: PaymentStatus,
        processed_at: datetime,
        failure_reason: str | None,
    ) -> bool:
        """Mark pending payment as terminal; idempotent if already processed."""

        stmt = (
            update(Payment)
            .where(
                and_(
                    Payment.id == payment_id,
                    Payment.status == PaymentStatus.PENDING,
                ),
            )
            .values(
                status=status,
                processed_at=processed_at,
                failure_reason=failure_reason,
            )
            .returning(Payment.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def update_webhook_result(
        self,
        *,
        payment_id: UUID,
        attempts: int,
        delivered: bool,
        last_error: str | None,
    ) -> None:
        values: dict[str, object] = {
            "webhook_attempts": attempts,
            "webhook_last_error": last_error,
        }
        if delivered:
            values["webhook_delivered_at"] = datetime.now(UTC)

        await self._session.execute(
            update(Payment)
            .where(Payment.id == payment_id)
            .values(**values),
        )

    async def acquire_webhook_lock(
        self,
        *,
        payment_id: UUID,
        lock_id: str,
        lock_ttl_seconds: int,
    ) -> bool:
        """Acquire lock for webhook delivery to avoid duplicate side effects.

        The lock is acquired if no lock exists, if previous lock is stale, or if
        lock is already owned by the same lock_id.
        """

        lock_expired_before = datetime.now(UTC) - timedelta(seconds=lock_ttl_seconds)
        stmt = (
            update(Payment)
            .where(
                and_(
                    Payment.id == payment_id,
                    or_(
                        Payment.webhook_lock_id.is_(None),
                        Payment.webhook_locked_at.is_(None),
                        Payment.webhook_locked_at < lock_expired_before,
                        Payment.webhook_lock_id == lock_id,
                    ),
                ),
            )
            .values(
                webhook_lock_id=lock_id,
                webhook_locked_at=datetime.now(UTC),
            )
            .returning(Payment.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def release_webhook_lock(self, *, payment_id: UUID, lock_id: str) -> None:
        """Release webhook lock only if owned by the caller lock_id."""

        await self._session.execute(
            update(Payment)
            .where(and_(Payment.id == payment_id, Payment.webhook_lock_id == lock_id))
            .values(
                webhook_lock_id=None,
                webhook_locked_at=None,
            ),
        )


class OutboxRepository:
    """Repository for outbox events with lock-based polling."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_event(
        self,
        *,
        event_type: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
    ) -> OutboxEvent:
        event = OutboxEvent(
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status=OutboxStatus.PENDING,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def acquire_pending_batch(
        self,
        *,
        lock_id: str,
        batch_size: int,
        lock_ttl_seconds: int,
    ) -> list[OutboxEvent]:
        """Lock a deterministic batch of unpublished events.

        We mark events as IN_PROGRESS with lock metadata in a single SQL statement,
        then load those rows back. This prevents two relay loops from publishing the
        same event concurrently.
        """

        lock_expired_before = datetime.now(UTC) - timedelta(seconds=lock_ttl_seconds)
        candidates_query = (
            select(OutboxEvent.id)
            .where(
                and_(
                    OutboxEvent.status.in_([OutboxStatus.PENDING, OutboxStatus.IN_PROGRESS]),
                    or_(
                        OutboxEvent.locked_at.is_(None),
                        OutboxEvent.locked_at < lock_expired_before,
                    ),
                ),
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(batch_size)
        )
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name != "sqlite":
            candidates_query = candidates_query.with_for_update(skip_locked=True)

        if dialect_name == "sqlite":
            candidate_ids_result = await self._session.execute(candidates_query)
            candidate_ids = list(candidate_ids_result.scalars())
            if not candidate_ids:
                return []
            await self._session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id.in_(candidate_ids))
                .values(
                    status=OutboxStatus.IN_PROGRESS,
                    lock_id=lock_id,
                    locked_at=datetime.now(UTC),
                ),
            )
            rows = await self._session.execute(
                select(OutboxEvent)
                .where(and_(OutboxEvent.id.in_(candidate_ids), OutboxEvent.lock_id == lock_id))
                .order_by(OutboxEvent.created_at.asc()),
            )
            return list(rows.scalars())

        lock_stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(candidates_query))
            .values(
                status=OutboxStatus.IN_PROGRESS,
                lock_id=lock_id,
                locked_at=datetime.now(UTC),
            )
            .returning(OutboxEvent)
        )
        locked = await self._session.execute(lock_stmt)
        return list(locked.scalars())

    async def mark_published(self, *, event_id: UUID) -> None:
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.PUBLISHED,
                published_at=datetime.now(UTC),
                lock_id=None,
                locked_at=None,
                last_error=None,
            ),
        )

    async def mark_publish_failed(self, *, event_id: UUID, error: str) -> None:
        await self._session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status=OutboxStatus.PENDING,
                attempts=OutboxEvent.attempts + 1,
                lock_id=None,
                locked_at=None,
                last_error=error,
            ),
        )
