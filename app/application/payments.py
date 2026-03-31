"""Application services for payment workflows."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Payment
from app.domain.enums import Currency, EventType
from app.domain.errors import PaymentNotFoundError
from app.infrastructure.repositories import OutboxRepository, PaymentRepository
from app.schemas.events import PaymentCreatedEvent

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CreatePaymentInput:
    """Input DTO for creating payment."""

    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    idempotency_key: str
    webhook_url: str


class PaymentService:
    """Use case service for payment create/get flow."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._payments = PaymentRepository(session)
        self._outbox = OutboxRepository(session)

    async def create_payment(self, payload: CreatePaymentInput) -> Payment:
        """Create payment with transactional outbox write.

        Payment row and outbox event are written in the same transaction.
        If idempotency key already exists we return the existing payment and skip outbox write.
        """

        async with self._session.begin():
            payment, created_now = await self._payments.upsert_pending(
                amount=payload.amount,
                currency=payload.currency,
                description=payload.description,
                metadata=payload.metadata,
                idempotency_key=payload.idempotency_key,
                webhook_url=payload.webhook_url,
            )

            if created_now:
                event = PaymentCreatedEvent(
                    event_id=uuid4(),
                    payment_id=payment.id,
                    idempotency_key=payment.idempotency_key,
                    amount=payment.amount,
                    currency=payment.currency,
                    description=payment.description,
                    metadata=payment.metadata_json,
                    webhook_url=payment.webhook_url,
                    created_at=payment.created_at,
                )
                await self._outbox.create_event(
                    event_type=EventType.PAYMENT_CREATED,
                    aggregate_id=payment.id,
                    payload=event.model_dump(mode="json"),
                )
                logger.info(
                    "Payment created and outbox event persisted",
                    extra={
                        "payment_id": str(payment.id),
                        "idempotency_key": payment.idempotency_key,
                    },
                )
            else:
                logger.info(
                    "Idempotent create request returned existing payment",
                    extra={
                        "payment_id": str(payment.id),
                        "idempotency_key": payment.idempotency_key,
                    },
                )

            return payment

    async def get_payment(self, payment_id: UUID) -> Payment:
        payment = await self._payments.get_by_id(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        return payment
