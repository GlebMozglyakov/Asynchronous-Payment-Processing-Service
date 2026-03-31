"""Unit tests for API schema validation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.schemas.common import PaymentCreateRequest

pytestmark = pytest.mark.unit


def test_payment_create_request_accepts_valid_payload() -> None:
    payload = PaymentCreateRequest(
        amount=Decimal("100.50"),
        currency="USD",
        description="Order payment",
        metadata={"order_id": "123"},
        webhook_url="https://example.com/webhook",
    )
    assert payload.amount == Decimal("100.50")
    assert payload.currency == "USD"


@pytest.mark.parametrize("currency", ["GBP", "RUR", ""])
def test_payment_create_request_rejects_unsupported_currency(currency: str) -> None:
    with pytest.raises(ValidationError):
        PaymentCreateRequest(
            amount=Decimal("10.00"),
            currency=currency,
            description="test",
            metadata={"k": "v"},
            webhook_url="https://example.com/webhook",
        )


def test_payment_create_request_rejects_non_positive_amount() -> None:
    with pytest.raises(ValidationError):
        PaymentCreateRequest(
            amount=Decimal("0"),
            currency="EUR",
            description="test",
            metadata={"k": "v"},
            webhook_url="https://example.com/webhook",
        )


def test_payment_create_request_requires_metadata_object() -> None:
    with pytest.raises(ValidationError):
        PaymentCreateRequest(
            amount=Decimal("1.00"),
            currency="RUB",
            description="test",
            metadata=cast(Any, None),
            webhook_url="https://example.com/webhook",
        )


def test_payment_create_request_rejects_invalid_url() -> None:
    with pytest.raises(ValidationError):
        PaymentCreateRequest(
            amount=Decimal("1.00"),
            currency="RUB",
            description="test",
            metadata={"k": "v"},
            webhook_url="not-a-url",
        )
