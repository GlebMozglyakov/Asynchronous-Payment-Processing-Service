"""FastStream consumer runtime for payment processing events."""

from __future__ import annotations

import asyncio
import logging

from faststream import FastStream
from faststream.middlewares.acknowledgement.config import AckPolicy
from faststream.rabbit import RabbitMessage

from app.application.processor import PaymentProcessor
from app.config import get_settings
from app.db.session import SessionFactory
from app.domain.errors import NonRetryableProcessingError, RetryableProcessingError
from app.infrastructure.messaging import (
    broker,
    connect_and_setup_topology,
    dead_letter_exchange,
    payments_exchange,
    payments_queue,
    payments_routing_key,
    retry_exchange,
)
from app.logging import configure_logging
from app.schemas.events import PaymentCreatedEvent

settings = get_settings()
configure_logging(logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)


@broker.subscriber(
    queue=payments_queue,
    exchange=payments_exchange,
    ack_policy=AckPolicy.MANUAL,
)
async def consume_payment_created(event: PaymentCreatedEvent, message: RabbitMessage) -> None:
    """Consume newly created payment event and process it.

    Retries are implemented with explicit retry queue and exponential delay by TTL.
    After max attempts message is sent to dedicated DLQ exchange.
    """

    retry_count = int(message.headers.get("x-retry-count", "0"))

    if not broker.running:
        await connect_and_setup_topology()

    try:
        async with SessionFactory() as session:
            processor = PaymentProcessor(session)
            await processor.process(event)

        await message.ack()
        logger.info(
            "Payment message processed",
            extra={
                "payment_id": str(event.payment_id),
                "retry_count": retry_count,
            },
        )
    except RetryableProcessingError as exc:
        await _handle_retryable_error(event, message, retry_count, str(exc))
    except NonRetryableProcessingError as exc:
        await _publish_to_dlq(event, retry_count, str(exc))
        await message.ack()
    except Exception as exc:
        await _handle_retryable_error(event, message, retry_count, str(exc))


async def _handle_retryable_error(
    event: PaymentCreatedEvent,
    message: RabbitMessage,
    retry_count: int,
    error_message: str,
) -> None:
    if retry_count >= settings.consumer_retry_attempts - 1:
        await _publish_to_dlq(event, retry_count + 1, error_message)
        await message.ack()
        logger.error(
            "Message moved to DLQ after max retries",
            extra={
                "payment_id": str(event.payment_id),
                "retry_count": retry_count + 1,
                "error": error_message,
            },
        )
        return

    next_retry = retry_count + 1
    delay_seconds = settings.consumer_retry_base_delay_seconds * (2 ** (next_retry - 1))

    await broker.publish(
        message=event.model_dump(mode="json"),
        exchange=retry_exchange,
        routing_key=payments_routing_key,
        headers={
            "x-retry-count": str(next_retry),
            "x-last-error": error_message,
        },
        expiration=int(delay_seconds * 1000),
        persist=True,
    )
    await message.ack()
    logger.warning(
        "Message scheduled for retry",
        extra={
            "payment_id": str(event.payment_id),
            "retry_count": next_retry,
            "delay_seconds": delay_seconds,
            "error": error_message,
        },
    )


async def _publish_to_dlq(event: PaymentCreatedEvent, retry_count: int, error_message: str) -> None:
    await broker.publish(
        message=event.model_dump(mode="json"),
        exchange=dead_letter_exchange,
        routing_key=payments_routing_key,
        headers={
            "x-retry-count": str(retry_count),
            "x-last-error": error_message,
        },
        persist=True,
    )


app = FastStream(
    broker,
    on_startup=[connect_and_setup_topology],
)


def run() -> None:
    """CLI entrypoint for standalone consumer process."""

    asyncio.run(app.run())


if __name__ == "__main__":
    run()
