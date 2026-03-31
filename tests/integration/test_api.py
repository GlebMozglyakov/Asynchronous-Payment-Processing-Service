"""Integration tests for HTTP API endpoints and DB writes."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import OutboxEvent, Payment


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_payment_and_get_details(
    app_client: httpx.AsyncClient,
    integration_engine: async_sessionmaker[AsyncSession],
) -> None:
    headers = {
        "X-API-Key": "integration-api-key",
        "Idempotency-Key": "payment-1",
    }
    payload = {
        "amount": "125.50",
        "currency": "USD",
        "description": "Order #1",
        "metadata": {"order_id": "1"},
        "webhook_url": "https://merchant.local/webhook",
    }

    create_response = await app_client.post("/api/v1/payments", headers=headers, json=payload)

    assert create_response.status_code == 202
    created_body = create_response.json()
    payment_id = UUID(created_body["payment_id"])
    assert created_body["status"] == "pending"

    get_response = await app_client.get(
        f"/api/v1/payments/{payment_id}",
        headers={"X-API-Key": "integration-api-key"},
    )

    assert get_response.status_code == 200
    details = get_response.json()
    assert details["payment_id"] == str(payment_id)
    assert details["amount"] == "125.50"
    assert details["status"] == "pending"

    async with integration_engine() as session:
        payments = list((await session.execute(select(Payment))).scalars())
        outbox = list((await session.execute(select(OutboxEvent))).scalars())
        assert len(payments) == 1
        assert len(outbox) == 1
        assert outbox[0].aggregate_id == payment_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_payment_is_idempotent(
    app_client: httpx.AsyncClient,
    integration_engine: async_sessionmaker[AsyncSession],
) -> None:
    headers = {
        "X-API-Key": "integration-api-key",
        "Idempotency-Key": "same-key",
    }
    payload = {
        "amount": "42.00",
        "currency": "EUR",
        "description": "Idempotent",
        "metadata": {"order_id": "2"},
        "webhook_url": "https://merchant.local/webhook",
    }

    first = await app_client.post("/api/v1/payments", headers=headers, json=payload)
    second = await app_client.post("/api/v1/payments", headers=headers, json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["payment_id"] == second.json()["payment_id"]

    async with integration_engine() as session:
        payments = list((await session.execute(select(Payment))).scalars())
        outbox = list((await session.execute(select(OutboxEvent))).scalars())
        assert len(payments) == 1
        assert len(outbox) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_idempotent_requests_return_same_payment(
    app_client: httpx.AsyncClient,
    integration_engine: async_sessionmaker[AsyncSession],
) -> None:
    headers = {
        "X-API-Key": "integration-api-key",
        "Idempotency-Key": "parallel-key",
    }
    payload = {
        "amount": "10.00",
        "currency": "RUB",
        "description": "Parallel request",
        "metadata": {"order_id": "parallel"},
        "webhook_url": "https://merchant.local/webhook",
    }

    responses = await asyncio.gather(
        app_client.post("/api/v1/payments", headers=headers, json=payload),
        app_client.post("/api/v1/payments", headers=headers, json=payload),
    )

    assert all(resp.status_code == 202 for resp in responses)
    payment_ids = {resp.json()["payment_id"] for resp in responses}
    assert len(payment_ids) == 1

    async with integration_engine() as session:
        payments = list((await session.execute(select(Payment))).scalars())
        outbox = list((await session.execute(select(OutboxEvent))).scalars())
        assert len(payments) == 1
        assert len(outbox) == 1


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "wrong-key"},
    ],
)
async def test_authentication_is_required_for_endpoints(
    app_client: httpx.AsyncClient,
    headers: dict[str, str],
) -> None:
    response = await app_client.get("/health", headers=headers)
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_idempotency_key_returns_error(app_client: httpx.AsyncClient) -> None:
    payload = {
        "amount": "1.00",
        "currency": "USD",
        "description": "No idempotency",
        "metadata": {"order_id": "3"},
        "webhook_url": "https://merchant.local/webhook",
    }

    response = await app_client.post(
        "/api/v1/payments",
        headers={"X-API-Key": "integration-api-key"},
        json=payload,
    )

    assert response.status_code == 400
    assert response.json()["error"] == "missing_idempotency_key"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_healthcheck_requires_api_key_and_returns_service_info(
    app_client: httpx.AsyncClient,
) -> None:
    unauthorized = await app_client.get("/health")
    assert unauthorized.status_code == 401

    authorized = await app_client.get(
        "/health",
        headers={"X-API-Key": "integration-api-key"},
    )
    assert authorized.status_code == 200
    body = authorized.json()
    assert body["status"] == "ok"
    assert body["service"] == "Asynchronous Payment Processing Service"
    assert body["version"] == "0.1.0"
