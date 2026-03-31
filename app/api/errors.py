"""Centralized API error mapping and handlers."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from app.domain.errors import ApplicationError


def _error_payload(code: str, message: str) -> dict[str, str]:
    return {
        "error": code,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
    }


def register_error_handlers(app: FastAPI) -> None:
    """Register exception handlers used by HTTP endpoints."""

    @app.exception_handler(ApplicationError)
    async def handle_application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        status_code = status.HTTP_400_BAD_REQUEST
        if exc.code == "unauthorized":
            status_code = status.HTTP_401_UNAUTHORIZED
        elif exc.code == "payment_not_found":
            status_code = status.HTTP_404_NOT_FOUND

        return JSONResponse(
            status_code=status_code,
            content=_error_payload(exc.code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        for error in exc.errors():
            location = error.get("loc")
            if (
                isinstance(location, tuple)
                and len(location) >= 2
                and location[0] == "header"
                and location[1].lower() == "idempotency-key"
                and error.get("type") == "missing"
            ):
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=_error_payload(
                        "missing_idempotency_key",
                        "Idempotency-Key header is required",
                    ),
                )

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "message": "Request validation failed",
                "details": exc.errors(),
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
