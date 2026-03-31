"""Consumer-side payment processing workflow."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.gateway import PaymentGatewayEmulator
from app.config import get_settings
from app.domain.enums import PaymentStatus
from app.domain.errors import PaymentNotFoundError, RetryableProcessingError
from app.infrastructure.repositories import PaymentRepository
from app.infrastructure.webhook import WebhookClient, WebhookDeliveryError
from app.schemas.events import PaymentCreatedEvent, WebhookPayload

logger = logging.getLogger(__name__)


class PaymentProcessor:
    """Process payment event: gateway call, state update, webhook delivery."""

    def __init__(self, session: AsyncSession) -> None:
        settings = get_settings()
        self._session = session
        self._payment_repo = PaymentRepository(session)
        self._gateway = PaymentGatewayEmulator(
            sleep_min_seconds=settings.gateway_sleep_min_seconds,
            sleep_max_seconds=settings.gateway_sleep_max_seconds,
            success_rate=settings.gateway_success_rate,
        )
        self._webhook_client = WebhookClient(
            timeout_seconds=settings.webhook_timeout_seconds,
            max_attempts=settings.webhook_retry_attempts,
            base_delay_seconds=settings.webhook_retry_base_delay_seconds,
        )

    async def process(self, event: PaymentCreatedEvent) -> None:
        """Execute full payment processing in idempotent manner."""

        payment = await self._payment_repo.get_by_id(event.payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(event.payment_id))

        if payment.status != PaymentStatus.PENDING and payment.webhook_delivered_at is not None:
            logger.info(
                "Skipping message because payment already processed",
                extra={
                    "payment_id": str(payment.id),
                    "status": payment.status,
                },
            )
            return

        terminal_status: PaymentStatus
        processed_at: datetime
        failure_reason: str | None

        if payment.status == PaymentStatus.PENDING:
            gateway_result = await self._gateway.process()
            terminal_status = (
                PaymentStatus.SUCCEEDED if gateway_result.succeeded else PaymentStatus.FAILED
            )
            processed_at = datetime.now(UTC)
            failure_reason = gateway_result.error

            changed = await self._payment_repo.mark_processed(
                payment_id=payment.id,
                status=terminal_status,
                processed_at=processed_at,
                failure_reason=failure_reason,
            )
            await self._session.commit()

            if not changed:
                payment = await self._payment_repo.get_by_id(event.payment_id)
                if payment is None:
                    raise PaymentNotFoundError(str(event.payment_id))

                if payment.webhook_delivered_at is not None:
                    logger.info(
                        "Payment was already processed and webhook delivered by another worker",
                        extra={"payment_id": str(payment.id)},
                    )
                    return

                terminal_status = payment.status
                processed_at = payment.processed_at or datetime.now(UTC)
                failure_reason = payment.failure_reason
        else:
            terminal_status = payment.status
            processed_at = payment.processed_at or datetime.now(UTC)
            failure_reason = payment.failure_reason

        webhook_payload = WebhookPayload(
            payment_id=payment.id,
            status=terminal_status,
            amount=payment.amount,
            currency=payment.currency,
            description=payment.description,
            metadata=payment.metadata_json,
            processed_at=processed_at,
            failure_reason=failure_reason,
        )

        try:
            attempts = await self._webhook_client.send(payment.webhook_url, webhook_payload)
            await self._payment_repo.update_webhook_result(
                payment_id=payment.id,
                attempts=attempts,
                delivered=True,
                last_error=None,
            )
            await self._session.commit()
        except WebhookDeliveryError as exc:
            await self._payment_repo.update_webhook_result(
                payment_id=payment.id,
                attempts=get_settings().webhook_retry_attempts,
                delivered=False,
                last_error=str(exc),
            )
            await self._session.commit()
            raise RetryableProcessingError(str(exc)) from exc
