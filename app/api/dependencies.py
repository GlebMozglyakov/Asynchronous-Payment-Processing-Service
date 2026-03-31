"""FastAPI dependencies shared by route handlers."""

import secrets

from fastapi import Header, Request, Security
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings
from app.domain.errors import MissingIdempotencyKeyError, UnauthorizedError

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Static API key required for all endpoints",
)


async def require_api_key(request: Request, api_key: str | None = Security(api_key_header)) -> None:
    """Validate static API key for every endpoint."""

    settings: Settings = getattr(request.app.state, "settings", get_settings())
    if api_key is None or not secrets.compare_digest(api_key, settings.api_key):
        raise UnauthorizedError()


async def require_idempotency_key(
    idempotency_key: str = Header(alias="Idempotency-Key"),
) -> str:
    """Require and return idempotency key for POST /payments."""

    if not idempotency_key.strip():
        raise MissingIdempotencyKeyError()
    return idempotency_key.strip()
