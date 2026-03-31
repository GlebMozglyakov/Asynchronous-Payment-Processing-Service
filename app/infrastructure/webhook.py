"""Webhook client with retry and exponential backoff."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.infrastructure.retry import calculate_retry_delay_seconds
from app.schemas.events import WebhookPayload

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Raised when webhook failed after all retries."""


class WebhookClient:
    """Deliver webhook notifications with bounded retries."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_attempts: int,
        base_delay_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if base_delay_seconds <= 0:
            raise ValueError("base_delay_seconds must be > 0")

        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._client = client

    async def send(self, webhook_url: str, payload: WebhookPayload) -> int:
        """Send webhook with exponential retry and return attempts count."""

        async with self._get_client() as client:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await client.post(
                        webhook_url,
                        json=payload.model_dump(mode="json"),
                        timeout=self._timeout_seconds,
                    )
                    response.raise_for_status()
                    logger.info(
                        "Webhook delivered",
                        extra={
                            "webhook_url": webhook_url,
                            "attempt": attempt,
                        },
                    )
                    return attempt
                except (httpx.HTTPError, httpx.NetworkError) as exc:
                    logger.warning(
                        "Webhook delivery attempt failed",
                        extra={
                            "webhook_url": webhook_url,
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )
                    if attempt >= self._max_attempts:
                        break
                    await asyncio.sleep(
                        calculate_retry_delay_seconds(
                            base_delay_seconds=self._base_delay_seconds,
                            retry_number=attempt,
                        ),
                    )

        raise WebhookDeliveryError(
            f"Unable to deliver webhook to {webhook_url} after {self._max_attempts} attempts",
        )

    def _get_client(self) -> httpx.AsyncClient | _PassThroughAsyncClientContext:
        if self._client is not None:
            return _PassThroughAsyncClientContext(self._client)
        return httpx.AsyncClient()


class _PassThroughAsyncClientContext:
    """Allow externally managed httpx client to be used as async context manager."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        return None
