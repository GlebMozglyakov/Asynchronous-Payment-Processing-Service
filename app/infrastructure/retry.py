"""Retry policy helpers used by consumer and tests."""


def calculate_retry_delay_seconds(*, base_delay_seconds: float, retry_number: int) -> float:
    """Return exponential backoff delay for retry number starting from 1.

    Example with base=1s:
    - retry_number=1 -> 1s
    - retry_number=2 -> 2s
    - retry_number=3 -> 4s
    """

    if retry_number < 1:
        raise ValueError("retry_number must be >= 1")
    if base_delay_seconds <= 0:
        raise ValueError("base_delay_seconds must be > 0")

    multiplier = float(2 ** (retry_number - 1))
    return base_delay_seconds * multiplier
