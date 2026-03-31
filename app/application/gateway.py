"""External payment gateway emulator used by consumer."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass


@dataclass(slots=True)
class GatewayResult:
    """Result of simulated payment provider call."""

    succeeded: bool
    error: str | None = None


class PaymentGatewayEmulator:
    """Simulate external payment processor with latency and probabilistic outcome."""

    def __init__(
        self,
        *,
        sleep_min_seconds: float,
        sleep_max_seconds: float,
        success_rate: float,
        random_source: random.Random | None = None,
    ) -> None:
        if sleep_min_seconds <= 0 or sleep_max_seconds <= 0:
            raise ValueError("Gateway delay values must be positive")
        if sleep_min_seconds > sleep_max_seconds:
            raise ValueError("sleep_min_seconds must be <= sleep_max_seconds")
        if not 0 < success_rate < 1:
            raise ValueError("success_rate must be in (0, 1)")

        self._sleep_min = sleep_min_seconds
        self._sleep_max = sleep_max_seconds
        self._success_rate = success_rate
        self._random = random_source or random.Random()

    async def process(self) -> GatewayResult:
        """Simulate gateway roundtrip and return deterministic structured result."""

        delay = self._random.uniform(self._sleep_min, self._sleep_max)
        await asyncio.sleep(delay)
        if self._random.random() <= self._success_rate:
            return GatewayResult(succeeded=True)
        return GatewayResult(succeeded=False, error="Gateway declined transaction")
