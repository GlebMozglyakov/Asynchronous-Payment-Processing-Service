"""Unit tests for outbox relay publication logic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OutboxEvent, Payment
from app.domain.enums import Currency, OutboxStatus, PaymentStatus
from app.infrastructure.outbox_relay import OutboxRelay

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_outbox_relay_publishes_and_marks_event(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    payment_id = uuid4()
    event_id = uuid4()

    async with db_session.begin():
        db_session.add(
            Payment(
                id=payment_id,
                amount=Decimal("20.00"),
                currency=Currency.USD,
                description="order",
                metadata_json={"order_id": "123"},
                status=PaymentStatus.PENDING,
                idempotency_key="idem-outbox",
                webhook_url="https://merchant.local/webhook",
            ),
        )
        db_session.add(
            OutboxEvent(
                id=uuid4(),
                event_type="payment.created",
                aggregate_id=payment_id,
                payload={
                    "event_id": str(event_id),
                    "payment_id": str(payment_id),
                    "idempotency_key": "idem-outbox",
                    "amount": "20.00",
                    "currency": "USD",
                    "description": "order",
                    "metadata": {"order_id": "123"},
                    "webhook_url": "https://merchant.local/webhook",
                    "created_at": datetime.now(UTC).isoformat(),
                },
                status=OutboxStatus.PENDING,
            ),
        )

    published: list[dict[str, object]] = []

    async def fake_publish(**kwargs: object) -> None:
        published.append(dict(kwargs))

    monkeypatch.setattr("app.infrastructure.outbox_relay.broker.publish", fake_publish)

    relay = OutboxRelay(session_factory=db_session_factory)
    processed = await relay._publish_once("lock-1")

    assert processed is True
    assert len(published) == 1
    assert published[0]["message_id"] == str(event_id)

    rows = list((await db_session.execute(select(OutboxEvent))).scalars())
    assert rows[0].status == OutboxStatus.PUBLISHED
    assert rows[0].published_at is not None
