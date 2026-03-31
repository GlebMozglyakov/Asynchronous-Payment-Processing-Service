"""Domain enums for payments and messaging."""

from enum import StrEnum


class Currency(StrEnum):
    """Supported ISO-like currency codes."""

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(StrEnum):
    """Payment lifecycle statuses."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OutboxStatus(StrEnum):
    """State of event publication from outbox."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PUBLISHED = "published"
    FAILED = "failed"


class EventType(StrEnum):
    """Known domain event types."""

    PAYMENT_CREATED = "payment.created"
