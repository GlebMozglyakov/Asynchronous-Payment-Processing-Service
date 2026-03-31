"""Unit tests for payment gateway emulator."""

from __future__ import annotations

import random

import pytest

from app.application.gateway import PaymentGatewayEmulator

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_gateway_success_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.application.gateway.asyncio.sleep", _fake_sleep)
    gateway = PaymentGatewayEmulator(
        sleep_min_seconds=2,
        sleep_max_seconds=5,
        success_rate=0.9,
        random_source=_StubRandom(uniform_value=2.5, random_value=0.1),
    )

    result = await gateway.process()

    assert result.succeeded is True
    assert result.error is None


@pytest.mark.asyncio
async def test_gateway_failure_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.application.gateway.asyncio.sleep", _fake_sleep)
    gateway = PaymentGatewayEmulator(
        sleep_min_seconds=2,
        sleep_max_seconds=5,
        success_rate=0.9,
        random_source=_StubRandom(uniform_value=4.2, random_value=0.95),
    )

    result = await gateway.process()

    assert result.succeeded is False
    assert result.error == "Gateway declined transaction"


def test_gateway_invalid_config_raises_value_error() -> None:
    with pytest.raises(ValueError):
        PaymentGatewayEmulator(
            sleep_min_seconds=5,
            sleep_max_seconds=1,
            success_rate=0.9,
            random_source=random.Random(1),
        )


async def _fake_sleep(_: float) -> None:
    return None


class _StubRandom(random.Random):
    def __init__(self, *, uniform_value: float, random_value: float) -> None:
        super().__init__(0)
        self._uniform_value = uniform_value
        self._random_value = random_value

    def uniform(self, a: float, b: float) -> float:
        return self._uniform_value

    def random(self) -> float:
        return self._random_value
