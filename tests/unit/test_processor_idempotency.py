"""Unit tests for payment processor idempotency around webhook delivery."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.processor import PaymentProcessor
from app.db.models import Payment
from app.domain.enums import Currency, PaymentStatus
from app.domain.errors import RetryableProcessingError
from app.schemas.events import PaymentCreatedEvent

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_processor_skips_gateway_when_payment_already_terminal_and_webhook_delivered(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = Payment(
        id=uuid4(),
        amount=Decimal("10.00"),
        currency=Currency.USD,
        description="terminal",
        metadata_json={"order_id": "t-1"},
        status=PaymentStatus.SUCCEEDED,
        idempotency_key="idem-terminal",
        webhook_url="https://merchant.local/webhook",
        processed_at=datetime.now(UTC),
        webhook_delivered_at=datetime.now(UTC),
    )
    db_session.add(payment)
    await db_session.commit()

    gateway_mock = AsyncMock()
    webhook_mock = AsyncMock()
    monkeypatch.setattr("app.application.processor.PaymentGatewayEmulator.process", gateway_mock)
    monkeypatch.setattr("app.application.processor.WebhookClient.send", webhook_mock)

    processor = PaymentProcessor(db_session)
    await processor.process(_event(payment.id, payment.idempotency_key, payment.webhook_url))

    gateway_mock.assert_not_awaited()
    webhook_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_processor_raises_retryable_error_when_webhook_lock_is_busy(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = Payment(
        id=uuid4(),
        amount=Decimal("11.00"),
        currency=Currency.USD,
        description="busy lock",
        metadata_json={"order_id": "t-2"},
        status=PaymentStatus.SUCCEEDED,
        idempotency_key="idem-busy",
        webhook_url="https://merchant.local/webhook",
        processed_at=datetime.now(UTC),
    )
    db_session.add(payment)
    await db_session.commit()

    monkeypatch.setattr(
        "app.infrastructure.repositories.PaymentRepository.acquire_webhook_lock",
        AsyncMock(return_value=False),
    )

    processor = PaymentProcessor(db_session)
    with pytest.raises(RetryableProcessingError):
        await processor.process(_event(payment.id, payment.idempotency_key, payment.webhook_url))


@pytest.mark.asyncio
async def test_processor_releases_webhook_lock_after_success(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = Payment(
        id=uuid4(),
        amount=Decimal("12.00"),
        currency=Currency.USD,
        description="release lock",
        metadata_json={"order_id": "t-3"},
        status=PaymentStatus.SUCCEEDED,
        idempotency_key="idem-release",
        webhook_url="https://merchant.local/webhook",
        processed_at=datetime.now(UTC),
    )
    db_session.add(payment)
    await db_session.commit()

    monkeypatch.setattr(
        "app.application.processor.WebhookClient.send",
        AsyncMock(return_value=1),
    )

    processor = PaymentProcessor(db_session)
    await processor.process(_event(payment.id, payment.idempotency_key, payment.webhook_url))

    updated = await db_session.get(Payment, payment.id)
    assert updated is not None
    assert updated.webhook_lock_id is None
    assert updated.webhook_locked_at is None


def _event(
    payment_id: UUID,
    idempotency_key: str,
    webhook_url: str,
) -> PaymentCreatedEvent:
    return PaymentCreatedEvent(
        event_id=uuid4(),
        payment_id=payment_id,
        idempotency_key=idempotency_key,
        amount=Decimal("10.00"),
        currency=Currency.USD,
        description="event",
        metadata={"order_id": "event"},
        webhook_url=cast(Any, webhook_url),
        created_at=datetime.now(UTC),
    )
