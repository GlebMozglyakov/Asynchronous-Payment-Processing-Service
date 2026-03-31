"""Common schema components used across API and messaging."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Currency, PaymentStatus


class HealthResponse(BaseModel):
    """Service health payload returned by /health endpoint."""

    status: str
    service: str
    version: str
    timestamp: datetime


class PaymentCreateRequest(BaseModel):
    """Request schema for creating a payment."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "amount": "1500.00",
                "currency": "RUB",
                "description": "Order #123 payment",
                "metadata": {"order_id": "123", "customer_id": "abc"},
                "webhook_url": "https://merchant.example.com/webhooks/payments",
            },
        },
    )

    amount: Decimal = Field(gt=Decimal("0"), max_digits=18, decimal_places=2)
    currency: Currency
    description: str = Field(min_length=1, max_length=512)
    metadata: dict[str, Any]
    webhook_url: AnyHttpUrl

    @field_validator("metadata")
    @classmethod
    def ensure_metadata_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Metadata must be a JSON object, not null."""

        if value is None:
            raise ValueError("metadata must be a JSON object")
        return value


class PaymentAcceptedResponse(BaseModel):
    """Response schema returned after payment was accepted for processing."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "payment_id": "7ff44b4b-e78a-4bd9-a2ab-7d0772e80d16",
                "status": "pending",
                "created_at": "2026-03-31T12:00:00Z",
            },
        },
    )

    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetailsResponse(BaseModel):
    """Detailed payment view schema for retrieval endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "payment_id": "7ff44b4b-e78a-4bd9-a2ab-7d0772e80d16",
                "amount": "1500.00",
                "currency": "RUB",
                "description": "Order #123 payment",
                "metadata": {"order_id": "123", "customer_id": "abc"},
                "status": "succeeded",
                "idempotency_key": "order-123-create-payment",
                "webhook_url": "https://merchant.example.com/webhooks/payments",
                "failure_reason": None,
                "created_at": "2026-03-31T12:00:00Z",
                "processed_at": "2026-03-31T12:00:03Z",
            },
        },
    )

    payment_id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: AnyHttpUrl
    failure_reason: str | None
    created_at: datetime
    processed_at: datetime | None
