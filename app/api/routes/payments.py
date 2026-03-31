"""Payment API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_api_key, require_idempotency_key
from app.application.payments import CreatePaymentInput, PaymentService
from app.config import get_settings
from app.db.session import get_db_session
from app.schemas.common import (
    HealthResponse,
    PaymentAcceptedResponse,
    PaymentCreateRequest,
    PaymentDetailsResponse,
)

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PaymentAcceptedResponse,
    summary="Create payment",
    description="Accept payment for asynchronous processing and enqueue outbox event.",
)
async def create_payment(
    payload: PaymentCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str,
        Depends(require_idempotency_key, use_cache=True),
    ],
) -> PaymentAcceptedResponse:
    """Create new payment or return existing one by idempotency key."""

    service = PaymentService(session)
    payment = await service.create_payment(
        CreatePaymentInput(
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            metadata=payload.metadata,
            idempotency_key=idempotency_key,
            webhook_url=str(payload.webhook_url),
        ),
    )
    return PaymentAcceptedResponse(
        payment_id=payment.id,
        status=payment.status,
        created_at=payment.created_at,
    )


@router.get(
    "/{payment_id}",
    response_model=PaymentDetailsResponse,
    summary="Get payment details",
    description="Return full payment details and processing status.",
)
async def get_payment(
    payment_id: Annotated[UUID, Path(description="Payment identifier")],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PaymentDetailsResponse:
    """Return payment details by id."""

    service = PaymentService(session)
    payment = await service.get_payment(payment_id)
    return PaymentDetailsResponse(
        payment_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metadata=payment.metadata_json,
        status=payment.status,
        idempotency_key=payment.idempotency_key,
        webhook_url=payment.webhook_url,
        failure_reason=payment.failure_reason,
        created_at=payment.created_at,
        processed_at=payment.processed_at,
    )


health_router = APIRouter(tags=["health"], dependencies=[Depends(require_api_key)])


@health_router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness/readiness healthcheck",
    description="Returns service status for Docker and runtime probes.",
)
async def healthcheck() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.now(UTC),
    )
