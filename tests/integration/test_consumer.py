"""Integration tests for consumer processing and retry/DLQ logic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.consumer import _handle_retryable_error, consume_payment_created
from app.db.models import Payment
from app.domain.enums import Currency, PaymentStatus
from app.schemas.events import PaymentCreatedEvent


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consumer_processes_message_and_updates_status(
    monkeypatch: pytest.MonkeyPatch,
    integration_engine: async_sessionmaker[AsyncSession],
) -> None:
    payment = await _seed_payment(integration_engine, idempotency_key="consumer-ok")

    monkeypatch.setattr(
        "app.application.processor.PaymentGatewayEmulator.process",
        AsyncMock(return_value=_GatewayResultStub(succeeded=True, error=None)),
    )
    monkeypatch.setattr(
        "app.application.processor.WebhookClient.send",
        AsyncMock(return_value=1),
    )

    monkeypatch.setattr("app.consumer.connect_and_setup_topology", AsyncMock())
    monkeypatch.setattr("app.consumer.broker.running", True)

    monkeypatch.setattr("app.consumer.SessionFactory", integration_engine)

    event = _event(payment.id, payment.idempotency_key, payment.webhook_url)
    message = _MessageStub(headers={})

    await consume_payment_created(event, cast(Any, message))

    assert message.acked is True
    assert message.nacked is False

    async with integration_engine() as session:
        updated = await session.get(Payment, payment.id)
        assert updated is not None
        assert updated.status == PaymentStatus.SUCCEEDED
        assert updated.processed_at is not None
        assert updated.webhook_attempts == 1
        assert updated.webhook_delivered_at is not None
        assert updated.webhook_lock_id is None
        assert updated.webhook_locked_at is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consumer_retry_flow_publishes_to_retry_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _MessageStub(headers={"x-retry-count": "0"})
    event = _event(uuid4(), "idem-retry", "https://merchant.local/webhook")

    publish_mock = AsyncMock()
    monkeypatch.setattr("app.consumer.broker.publish", publish_mock)

    await _handle_retryable_error(event, cast(Any, message), 0, "temporary error")

    assert message.acked is True
    publish_mock.assert_awaited_once()
    assert publish_mock.await_args is not None
    kwargs = publish_mock.await_args.kwargs
    assert kwargs["headers"]["x-retry-count"] == "1"
    assert kwargs["expiration"] == 1000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consumer_moves_to_dlq_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _MessageStub(headers={"x-retry-count": "3"})
    event = _event(uuid4(), "idem-dlq", "https://merchant.local/webhook")

    publish_mock = AsyncMock()
    monkeypatch.setattr("app.consumer.broker.publish", publish_mock)

    await _handle_retryable_error(event, cast(Any, message), 3, "final error")

    assert message.acked is True
    publish_mock.assert_awaited_once()
    assert publish_mock.await_args is not None
    kwargs = publish_mock.await_args.kwargs
    assert kwargs["headers"]["x-retry-count"] == "3"
    assert kwargs["headers"]["x-last-error"] == "final error"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consumer_retry_uses_exponential_backoff_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _MessageStub(headers={"x-retry-count": "2"})
    event = _event(uuid4(), "idem-retry-ttl", "https://merchant.local/webhook")

    publish_mock = AsyncMock()
    monkeypatch.setattr("app.consumer.broker.publish", publish_mock)

    await _handle_retryable_error(event, cast(Any, message), 2, "temporary error")

    publish_mock.assert_awaited_once()
    assert publish_mock.await_args is not None
    kwargs = publish_mock.await_args.kwargs
    assert kwargs["headers"]["x-retry-count"] == "3"
    assert kwargs["expiration"] == 4000


async def _seed_payment(
    engine: async_sessionmaker[AsyncSession],
    *,
    idempotency_key: str,
) -> Payment:
    payment_id = uuid4()
    payment = Payment(
        id=payment_id,
        amount=Decimal("30.00"),
        currency=Currency.USD,
        description="consumer test",
        metadata_json={"order_id": "consumer"},
        status=PaymentStatus.PENDING,
        idempotency_key=idempotency_key,
        webhook_url="https://merchant.local/webhook",
    )
    async with engine() as session, session.begin():
        session.add(payment)

    async with engine() as session:
        loaded = await session.get(Payment, payment_id)
        assert loaded is not None
        return loaded


def _event(
    payment_id: UUID,
    idempotency_key: str,
    webhook_url: str,
) -> PaymentCreatedEvent:
    return PaymentCreatedEvent(
        event_id=uuid4(),
        payment_id=payment_id,
        idempotency_key=idempotency_key,
        amount=Decimal("30.00"),
        currency=Currency.USD,
        description="consumer test",
        metadata={"order_id": "consumer"},
        webhook_url=cast(Any, webhook_url),
        created_at=datetime.now(UTC),
    )


class _GatewayResultStub:
    def __init__(self, *, succeeded: bool, error: str | None) -> None:
        self.succeeded = succeeded
        self.error = error


class _MessageStub:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.acked = False
        self.nacked = False

    async def ack(self) -> None:
        self.acked = True

    async def nack(self, *, requeue: bool = True) -> None:
        self.nacked = True
