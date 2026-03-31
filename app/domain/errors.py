"""Domain and application level exceptions."""


class ApplicationError(Exception):
    """Base application error."""

    def __init__(self, message: str, *, code: str = "application_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class UnauthorizedError(ApplicationError):
    """Raised when API key is missing or invalid."""

    def __init__(self, message: str = "Invalid API key") -> None:
        super().__init__(message, code="unauthorized")


class MissingIdempotencyKeyError(ApplicationError):
    """Raised when create payment request has no idempotency key."""

    def __init__(self, message: str = "Idempotency-Key header is required") -> None:
        super().__init__(message, code="missing_idempotency_key")


class PaymentNotFoundError(ApplicationError):
    """Raised when requested payment does not exist."""

    def __init__(self, payment_id: str) -> None:
        super().__init__(f"Payment '{payment_id}' was not found", code="payment_not_found")


class InfrastructureError(ApplicationError):
    """Raised for infrastructure-level failures."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="infrastructure_error")


class RetryableProcessingError(ApplicationError):
    """Consumer error that should trigger message retry."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="retryable_processing_error")


class NonRetryableProcessingError(ApplicationError):
    """Consumer error that should go directly to DLQ."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="non_retryable_processing_error")
