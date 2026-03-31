"""Internal event contracts for outbox and consumer flow."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from app.domain.enums import Currency, EventType, PaymentStatus


class PaymentCreatedEvent(BaseModel):
    """Event pushed to RabbitMQ when payment is created."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: EventType = EventType.PAYMENT_CREATED
    payment_id: UUID
    idempotency_key: str
    amount: Decimal = Field(max_digits=18, decimal_places=2)
    currency: Currency
    description: str
    metadata: dict[str, Any]
    webhook_url: AnyHttpUrl
    created_at: datetime


class WebhookPayload(BaseModel):
    """Payload delivered to merchant webhook endpoint."""

    payment_id: UUID
    status: PaymentStatus
    amount: Decimal = Field(max_digits=18, decimal_places=2)
    currency: Currency
    description: str
    metadata: dict[str, Any]
    processed_at: datetime
    failure_reason: str | None
