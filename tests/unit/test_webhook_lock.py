"""Unit tests for webhook lock acquisition/release semantics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment
from app.domain.enums import Currency, PaymentStatus
from app.infrastructure.repositories import PaymentRepository

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_acquire_webhook_lock_first_time(db_session: AsyncSession) -> None:
    payment = await _seed_payment(db_session)
    repo = PaymentRepository(db_session)

    acquired = await repo.acquire_webhook_lock(
        payment_id=payment.id,
        lock_id="lock-a",
        lock_ttl_seconds=120,
    )
    await db_session.commit()

    assert acquired is True
    updated = await db_session.get(Payment, payment.id)
    assert updated is not None
    assert updated.webhook_lock_id == "lock-a"
    assert updated.webhook_locked_at is not None


@pytest.mark.asyncio
async def test_acquire_webhook_lock_fails_when_fresh_lock_exists(db_session: AsyncSession) -> None:
    payment = await _seed_payment(db_session)
    repo = PaymentRepository(db_session)

    first = await repo.acquire_webhook_lock(
        payment_id=payment.id,
        lock_id="lock-a",
        lock_ttl_seconds=120,
    )
    await db_session.commit()
    assert first is True

    second = await repo.acquire_webhook_lock(
        payment_id=payment.id,
        lock_id="lock-b",
        lock_ttl_seconds=120,
    )
    await db_session.commit()

    assert second is False


@pytest.mark.asyncio
async def test_acquire_webhook_lock_succeeds_when_stale_lock_exists(
    db_session: AsyncSession,
) -> None:
    payment = await _seed_payment(db_session)
    payment.webhook_lock_id = "stale-lock"
    payment.webhook_locked_at = datetime.now(UTC) - timedelta(seconds=999)
    await db_session.commit()

    repo = PaymentRepository(db_session)
    acquired = await repo.acquire_webhook_lock(
        payment_id=payment.id,
        lock_id="new-lock",
        lock_ttl_seconds=120,
    )
    await db_session.commit()

    assert acquired is True
    updated = await db_session.get(Payment, payment.id)
    assert updated is not None
    assert updated.webhook_lock_id == "new-lock"


@pytest.mark.asyncio
async def test_release_webhook_lock_only_owner_can_release(db_session: AsyncSession) -> None:
    payment = await _seed_payment(db_session)
    payment.webhook_lock_id = "owner-lock"
    payment.webhook_locked_at = datetime.now(UTC)
    await db_session.commit()

    repo = PaymentRepository(db_session)
    await repo.release_webhook_lock(payment_id=payment.id, lock_id="another-lock")
    await db_session.commit()

    unchanged = await db_session.get(Payment, payment.id)
    assert unchanged is not None
    assert unchanged.webhook_lock_id == "owner-lock"

    await repo.release_webhook_lock(payment_id=payment.id, lock_id="owner-lock")
    await db_session.commit()

    released = await db_session.get(Payment, payment.id)
    assert released is not None
    assert released.webhook_lock_id is None
    assert released.webhook_locked_at is None


async def _seed_payment(db_session: AsyncSession) -> Payment:
    payment = Payment(
        id=uuid4(),
        amount=Decimal("50.00"),
        currency=Currency.USD,
        description="webhook lock test",
        metadata_json={"order_id": "wl-1"},
        status=PaymentStatus.PENDING,
        idempotency_key=f"idem-{uuid4()}",
        webhook_url="https://merchant.local/webhook",
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)
    return payment
