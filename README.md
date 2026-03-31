# Asynchronous Payment Processing Service

Production-like asynchronous payment processing microservice built for a backend engineering test assignment.

The service accepts payment creation requests, guarantees idempotent API behavior, persists events with the outbox pattern, publishes them to RabbitMQ, processes events in a single consumer, and delivers webhook notifications with robust retry behavior.

## Highlights

- `POST /api/v1/payments` with mandatory `Idempotency-Key`
- `GET /api/v1/payments/{payment_id}`
- `X-API-Key` required for all endpoints (including `/health`)
- Transactional outbox (`payments` + `outbox` in one DB transaction)
- RabbitMQ topology: main queue, retry queue, DLQ
- Single consumer with bounded retries and exponential backoff
- External gateway emulation: 2-5s latency, ~90% success / ~10% failure
- Webhook delivery retries + DB lock to prevent duplicate side effects
- Alembic migrations, Docker Compose stack, OpenAPI/Swagger, healthcheck
- Unit + integration tests, linting, formatting, type-checking

## Technology Stack

- Python 3.12
- FastAPI
- Pydantic v2
- SQLAlchemy 2.0 (async)
- PostgreSQL
- RabbitMQ + FastStream
- Alembic
- pytest / pytest-asyncio / httpx
- Ruff / mypy
- Docker / docker-compose

## Architecture

### End-to-end flow

1. Client calls `POST /api/v1/payments` with `Idempotency-Key`.
2. API service writes:
   - payment row (`payments`),
   - domain event row (`outbox`),
   in a single DB transaction.
3. Background outbox relay polls pending outbox rows and publishes to RabbitMQ.
4. Consumer receives `payment.created` event and executes processing workflow:
   - gateway emulation,
   - payment status update,
   - webhook delivery.
5. If processing fails, message is republished to retry queue with exponential TTL.
6. After retry limit is reached, message is moved to DLQ.

### Service boundaries

- `app/api/*`: HTTP transport layer (routing, dependencies, error mapping)
- `app/application/*`: business workflows (payment creation, processing orchestration)
- `app/infrastructure/*`: Rabbit topology, outbox relay, repositories, webhook client
- `app/db/*`: ORM models and session management
- `app/domain/*`: enums and domain-level exceptions

### Outbox guarantees

- `payments` and `outbox` are written atomically.
- Outbox events are marked `published` only after successful publish to RabbitMQ.
- Relay uses lock metadata to avoid concurrent duplicate publication.

### Idempotency guarantees

- API-level idempotency enforced by mandatory `Idempotency-Key`.
- DB-level idempotency enforced by unique constraint on `payments.idempotency_key`.
- Concurrent identical create requests return the same payment.

### Retry and DLQ guarantees

- Consumer uses explicit retry queue (not infinite broker requeue).
- Retry count is tracked via `x-retry-count` header.
- Delays are exponential (`base * 2^(n-1)`).
- Message goes to DLQ when max retry count is reached.

### Webhook side-effect safety

- Webhook delivery is additionally guarded by DB lock fields:
  - `webhook_lock_id`
  - `webhook_locked_at`
- This prevents duplicate webhook side effects on concurrent redelivery.

## Repository Structure

```text
.
  app/
    api/
    application/
    db/
    domain/
    infrastructure/
    consumer.py
    main.py
  alembic/
    versions/
  tests/
    unit/
    integration/
  .env.example
  alembic.ini
  docker-compose.yml
  Dockerfile
  Makefile
  pyproject.toml
  README.md
```

## Environment Setup

The compose setup uses `.env.example` directly for `api` and `consumer` services.

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Service name in metadata/health |
| `APP_VERSION` | Service version |
| `ENVIRONMENT` | Runtime environment flag |
| `DEBUG` | Debug logging mode |
| `API_HOST` | API bind host |
| `API_PORT` | API bind port |
| `API_KEY` | Static API key for all endpoints |
| `DATABASE_URL` | Async SQLAlchemy DB URL |
| `RABBITMQ_URL` | RabbitMQ connection URL |
| `PAYMENTS_EXCHANGE` | Main exchange for new payment events |
| `PAYMENTS_ROUTING_KEY` | Routing key for payment events |
| `PAYMENTS_QUEUE` | Main processing queue |
| `PAYMENTS_RETRY_EXCHANGE` | Retry exchange |
| `PAYMENTS_RETRY_QUEUE` | Retry queue |
| `PAYMENTS_DLX_EXCHANGE` | Dead-letter exchange |
| `PAYMENTS_DLQ` | Dead-letter queue |
| `ENABLE_BROKER_STARTUP` | Enables broker connect on API startup |
| `ENABLE_OUTBOX_RELAY` | Enables outbox relay in API process |
| `CONSUMER_RETRY_ATTEMPTS` | Max retry count before DLQ |
| `CONSUMER_RETRY_BASE_DELAY_SECONDS` | Base delay for consumer retry backoff |
| `OUTBOX_POLL_INTERVAL_SECONDS` | Relay poll interval |
| `OUTBOX_BATCH_SIZE` | Relay publish batch size |
| `OUTBOX_LOCK_TTL_SECONDS` | Outbox lock TTL |
| `WEBHOOK_TIMEOUT_SECONDS` | Webhook request timeout |
| `WEBHOOK_RETRY_ATTEMPTS` | Webhook retry attempts |
| `WEBHOOK_RETRY_BASE_DELAY_SECONDS` | Base delay for webhook retry |
| `WEBHOOK_LOCK_TTL_SECONDS` | DB lock TTL for webhook side effects |
| `GATEWAY_SLEEP_MIN_SECONDS` | Gateway emulator min latency |
| `GATEWAY_SLEEP_MAX_SECONDS` | Gateway emulator max latency |
| `GATEWAY_SUCCESS_RATE` | Gateway success probability |

## Quick Start (Docker)

1. Review `.env.example` (especially `API_KEY`).
2. Start stack:

```bash
make up
```

3. Open docs:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

4. Stop stack:

```bash
make down
```

## Local Development (without app containers)

1. Install dependencies:

```bash
make install-dev
```

2. Start infra (PostgreSQL + RabbitMQ) via Docker Compose if needed.
3. Apply migrations:

```bash
make migrate
```

4. Run API:

```bash
make run-api
```

5. Run consumer (separate terminal):

```bash
make run-consumer
```

## API Examples

Use `API_KEY` from `.env.example`.

### Healthcheck

```bash
curl -X GET "http://localhost:8000/health" \
  -H "X-API-Key: change-me-api-key"
```

### Create Payment

```bash
curl -X POST "http://localhost:8000/api/v1/payments" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-api-key" \
  -H "Idempotency-Key: order-123-create" \
  -d '{
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Order #123",
    "metadata": {"order_id": "123", "customer_id": "abc"},
    "webhook_url": "https://merchant.example.com/webhooks/payments"
  }'
```

### Get Payment

```bash
curl -X GET "http://localhost:8000/api/v1/payments/<payment_id>" \
  -H "X-API-Key: change-me-api-key"
```

## Quality Commands

### Tests

```bash
make test
make test-unit
make test-integration
```

### Lint / Format / Type-check

```bash
make lint
make format
make type-check
```

## How to Validate Main Scenario

1. Start stack (`make up`).
2. Create payment via `POST /api/v1/payments`.
3. Observe logs:

```bash
make logs
```

4. Check queues in RabbitMQ UI: `http://localhost:15672`
   - `payments.new`
   - `payments.new.retry`
   - `payments.new.dlq`
5. Query payment status with `GET /api/v1/payments/{payment_id}`.

## Engineering Trade-offs

- Outbox relay runs in API process to keep deployment topology minimal and test-task scope pragmatic.
- Retry/DLQ logic is explicit and bounded instead of relying on opaque broker redelivery behavior.
- Integration tests focus on service contracts and critical behavior under deterministic setup; full infra e2e can be added if required for production hardening.

## Submission Notes

- The project is intentionally production-like but not overengineered.
- Core guarantees (idempotency, outbox, retries, DLQ, authenticated API) are implemented explicitly and tested.
