"""Unit tests for API security dependency behavior."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.api.dependencies import require_api_key
from app.config import Settings
from app.domain.errors import UnauthorizedError

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_require_api_key_accepts_matching_key() -> None:
    app = FastAPI()
    app.state.settings = Settings(api_key="super-secret-key")
    request = Request({"type": "http", "app": app})

    await require_api_key(request, "super-secret-key")


@pytest.mark.asyncio
async def test_require_api_key_rejects_invalid_key() -> None:
    app = FastAPI()
    app.state.settings = Settings(api_key="super-secret-key")
    request = Request({"type": "http", "app": app})

    with pytest.raises(UnauthorizedError):
        await require_api_key(request, "wrong-key")


@pytest.mark.asyncio
async def test_require_api_key_rejects_missing_key() -> None:
    app = FastAPI()
    app.state.settings = Settings(api_key="super-secret-key")
    request = Request({"type": "http", "app": app})

    with pytest.raises(UnauthorizedError):
        await require_api_key(request, None)
