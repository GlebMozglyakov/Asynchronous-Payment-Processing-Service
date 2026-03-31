"""Unit tests for webhook client retry behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.domain.enums import Currency, PaymentStatus
from app.infrastructure.webhook import WebhookClient, WebhookDeliveryError
from app.schemas.events import WebhookPayload

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_webhook_client_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.infrastructure.webhook.asyncio.sleep", fake_sleep)

    transport = _SequenceTransport(
        [
            httpx.ConnectError("network down"),
            httpx.Response(status_code=500),
            httpx.Response(status_code=204),
        ],
    )
    async with httpx.AsyncClient(transport=transport) as client:
        webhook = WebhookClient(
            timeout_seconds=1,
            max_attempts=3,
            base_delay_seconds=0.5,
            client=client,
        )

        attempts = await webhook.send("https://merchant.local/webhook", _payload())

    assert attempts == 3
    assert sleeps == [0.5, 1.0]


@pytest.mark.asyncio
async def test_webhook_client_raises_after_max_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.infrastructure.webhook.asyncio.sleep", fake_sleep)

    transport = _SequenceTransport(
        [
            httpx.ConnectError("1"),
            httpx.ConnectError("2"),
            httpx.ConnectError("3"),
        ],
    )
    async with httpx.AsyncClient(transport=transport) as client:
        webhook = WebhookClient(
            timeout_seconds=1,
            max_attempts=3,
            base_delay_seconds=0.25,
            client=client,
        )

        with pytest.raises(WebhookDeliveryError):
            await webhook.send("https://merchant.local/webhook", _payload())

    assert sleeps == [0.25, 0.5]


def _payload() -> WebhookPayload:
    return WebhookPayload(
        payment_id=uuid4(),
        status=PaymentStatus.SUCCEEDED,
        amount=Decimal("10.00"),
        currency=Currency.USD,
        description="test",
        metadata={"order_id": "123"},
        processed_at=datetime.now(UTC),
        failure_reason=None,
    )


class _SequenceTransport(httpx.AsyncBaseTransport):
    def __init__(self, responses: list[Exception | httpx.Response]) -> None:
        self._responses = responses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return httpx.Response(
            status_code=result.status_code,
            headers=result.headers,
            content=result.content,
            request=request,
        )
