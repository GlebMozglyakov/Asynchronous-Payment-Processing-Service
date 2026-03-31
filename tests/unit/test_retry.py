"""Unit tests for shared retry backoff calculations."""

from __future__ import annotations

import pytest

from app.infrastructure.retry import calculate_retry_delay_seconds

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("base", "retry_number", "expected"),
    [
        (1.0, 1, 1.0),
        (1.0, 2, 2.0),
        (1.0, 3, 4.0),
        (0.5, 3, 2.0),
    ],
)
def test_calculate_retry_delay_seconds(base: float, retry_number: int, expected: float) -> None:
    assert calculate_retry_delay_seconds(
        base_delay_seconds=base,
        retry_number=retry_number,
    ) == expected


def test_calculate_retry_delay_seconds_validates_arguments() -> None:
    with pytest.raises(ValueError):
        calculate_retry_delay_seconds(base_delay_seconds=0.0, retry_number=1)

    with pytest.raises(ValueError):
        calculate_retry_delay_seconds(base_delay_seconds=1.0, retry_number=0)
