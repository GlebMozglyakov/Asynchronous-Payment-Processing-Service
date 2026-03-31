"""Integration tests for RabbitMQ topology declarations and queue contracts."""

from __future__ import annotations

import pytest

from app.infrastructure import messaging


@pytest.mark.integration
@pytest.mark.asyncio
async def test_setup_topology_declares_required_exchanges_and_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class _DeclaredQueue:
        def __init__(self, name: str) -> None:
            self.name = name

        async def bind(self, exchange: object, *, routing_key: str) -> None:
            exchange_name = getattr(exchange, "name", "")
            calls.append((f"bind:{self.name}", f"{exchange_name}:{routing_key}"))

    async def fake_declare_exchange(exchange: object) -> object:
        name = getattr(exchange, "name", "")
        calls.append(("declare_exchange", name))
        return exchange

    async def fake_declare_queue(queue: object) -> _DeclaredQueue:
        name = getattr(queue, "name", "")
        calls.append(("declare_queue", name))
        return _DeclaredQueue(name)

    monkeypatch.setattr(messaging.broker, "declare_exchange", fake_declare_exchange)
    monkeypatch.setattr(messaging.broker, "declare_queue", fake_declare_queue)

    await messaging.setup_rabbitmq_topology()

    assert ("declare_exchange", messaging.payments_exchange.name) in calls
    assert ("declare_exchange", messaging.retry_exchange.name) in calls
    assert ("declare_exchange", messaging.dead_letter_exchange.name) in calls
    assert ("declare_queue", messaging.payments_queue.name) in calls
    assert ("declare_queue", messaging.payments_retry_queue.name) in calls
    assert ("declare_queue", messaging.payments_dlq.name) in calls

    assert (
        f"bind:{messaging.payments_queue.name}",
        f"{messaging.payments_exchange.name}:{messaging.payments_routing_key}",
    ) in calls
    assert (
        f"bind:{messaging.payments_retry_queue.name}",
        f"{messaging.retry_exchange.name}:{messaging.payments_routing_key}",
    ) in calls
    assert (
        f"bind:{messaging.payments_dlq.name}",
        f"{messaging.dead_letter_exchange.name}:{messaging.payments_routing_key}",
    ) in calls
