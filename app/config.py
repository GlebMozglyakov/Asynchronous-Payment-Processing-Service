"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized runtime settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Asynchronous Payment Processing Service"
    app_version: str = "0.1.0"
    environment: Literal["local", "dev", "test", "prod"] = "local"
    debug: bool = False

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = Field(default="change-me", min_length=8)

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/payments"

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    payments_exchange: str = "payments.exchange"
    payments_routing_key: str = "payments.new"
    payments_queue: str = "payments.new"
    payments_retry_exchange: str = "payments.retry"
    payments_retry_queue: str = "payments.new.retry"
    payments_dlx_exchange: str = "payments.dlx"
    payments_dlq: str = "payments.new.dlq"
    enable_broker_startup: bool = True
    enable_outbox_relay: bool = True
    consumer_retry_attempts: int = 3
    consumer_retry_base_delay_seconds: float = 1.0

    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 100
    outbox_lock_ttl_seconds: int = 60

    webhook_timeout_seconds: float = 3.0
    webhook_retry_attempts: int = 3
    webhook_retry_base_delay_seconds: float = 1.0

    gateway_sleep_min_seconds: float = 2.0
    gateway_sleep_max_seconds: float = 5.0
    gateway_success_rate: float = 0.9

    # Optional URL for integration tests when webhook receiver lives outside app.
    test_webhook_url: AnyHttpUrl | None = None


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""

    return Settings()
