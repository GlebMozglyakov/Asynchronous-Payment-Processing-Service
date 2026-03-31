"""Unit tests for payment service and idempotency behavior."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.payments import CreatePaymentInput, PaymentService
from app.db.models import OutboxEvent, Payment
from app.domain.enums import Currency, PaymentStatus

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_create_payment_creates_payment_and_outbox(db_session: AsyncSession) -> None:
    service = PaymentService(db_session)

    created = await service.create_payment(_input("idem-1"))

    payment = await db_session.get(Payment, created.id)
    assert payment is not None
    assert payment.status == PaymentStatus.PENDING

    outbox_rows = list((await db_session.execute(_select_all_outbox())).scalars())
    assert len(outbox_rows) == 1
    assert outbox_rows[0].aggregate_id == created.id


@pytest.mark.asyncio
async def test_create_payment_is_idempotent_by_key(db_session: AsyncSession) -> None:
    service = PaymentService(db_session)

    first = await service.create_payment(_input("idem-shared"))
    second = await service.create_payment(_input("idem-shared"))

    assert first.id == second.id

    payments = list((await db_session.execute(_select_all_payments())).scalars())
    outbox_rows = list((await db_session.execute(_select_all_outbox())).scalars())
    assert len(payments) == 1
    assert len(outbox_rows) == 1


def _input(idempotency_key: str) -> CreatePaymentInput:
    return CreatePaymentInput(
        amount=Decimal("100.00"),
        currency=Currency.USD,
        description="test payment",
        metadata={"order_id": "o1"},
        idempotency_key=idempotency_key,
        webhook_url="https://merchant.local/webhook",
    )


def _select_all_payments():
    from sqlalchemy import select

    return select(Payment)


def _select_all_outbox():
    from sqlalchemy import select

    return select(OutboxEvent)
