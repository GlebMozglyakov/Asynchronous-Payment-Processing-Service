# Asynchronous Payment Processing Service

Production-like microservice for asynchronous payment processing with transactional outbox, RabbitMQ delivery guarantees, idempotent create API, consumer retries, webhook retries, and DLQ handling.

## Stack

- FastAPI
- Pydantic v2
- SQLAlchemy 2.0 (async)
- PostgreSQL
- RabbitMQ + FastStream
- Alembic
- Docker + docker-compose
- pytest / pytest-asyncio / httpx
- ruff / mypy

## What is implemented

- `POST /api/v1/payments` (requires `X-API-Key` and `Idempotency-Key`, returns `202 Accepted`)
- `GET /api/v1/payments/{payment_id}`
- `GET /health`
- Static API key auth on all endpoints
- Payment idempotency with DB unique constraint + upsert logic
- Transactional write of `payments` and `outbox`
- Outbox relay loop in API process (no extra container required)
- RabbitMQ topology with main queue, retry queue, and DLQ
- Single consumer that processes payment and sends webhook
- Gateway emulator (2-5 seconds, 90% success / 10% fail)
- Webhook client with 3 attempts + exponential backoff
- Consumer retry with exponential delays and explicit DLQ routing after max retries
- Unit + integration tests

## Architecture overview

Flow:

1. API receives payment creation request.
2. Service writes `payments` and `outbox` in one DB transaction.
3. Outbox relay polls pending outbox rows and publishes to RabbitMQ (`payments.exchange` + `payments.new`).
4. Consumer receives message from `payments.new`.
5. Consumer calls gateway emulator (2-5 seconds, 90/10), updates payment status.
6. Consumer sends webhook with retry/backoff.
7. If processing fails, message is sent to retry queue with TTL-based delay; after 3 attempts it goes to DLQ.

### RabbitMQ topology

- `payments.exchange` (direct)
  - queue `payments.new`
- `payments.retry` (direct)
  - queue `payments.new.retry` with dead-letter to `payments.exchange`
- `payments.dlx` (direct)
  - queue `payments.new.dlq`

### Retry and DLQ policy

- Webhook retry: 3 attempts, delays `1s`, `2s`, `4s` (configurable).
- Consumer message retry: if processing raises retryable error, message is republished to retry exchange with TTL (`1s`, `2s`, `4s`).
- After third retry is exhausted, message is published to DLQ.

### Idempotency policy

- `Idempotency-Key` is mandatory for payment creation.
- `payments.idempotency_key` has unique constraint.
- Creation uses `INSERT ... ON CONFLICT DO NOTHING` and returns existing payment if duplicate key is used.
- Parallel identical requests return the same payment and do not create duplicate outbox messages.

## Repository structure

```text
.
  app/
    api/
      routes/
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

## Environment variables

Copy `.env.example` to `.env` and adjust values if needed.

Critical settings:

- `API_KEY`
- `DATABASE_URL`
- `RABBITMQ_URL`
- `ENABLE_OUTBOX_RELAY`
- `WEBHOOK_RETRY_ATTEMPTS`
- `CONSUMER_RETRY_ATTEMPTS`

## Local run (without Docker)

1. Install dependencies:

```bash
make install-dev
```

2. Start PostgreSQL and RabbitMQ locally (or via docker compose only for infra).

3. Run migrations:

```bash
make migrate
```

4. Start API:

```bash
make run-api
```

5. Start consumer in another terminal:

```bash
make run-consumer
```

## Docker run

1. Copy env file:

```bash
cp .env.example .env
```

2. Start all services:

```bash
make up
```

3. Apply migrations inside API container:

```bash
docker compose exec api python -m alembic upgrade head
```

4. Check API docs:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

5. Stop services:

```bash
make down
```

## API examples

Use same API key as in `.env`.

### Healthcheck

```bash
curl -X GET "http://localhost:8000/health" \
  -H "X-API-Key: change-me-api-key"
```

### Create payment

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

### Get payment

```bash
curl -X GET "http://localhost:8000/api/v1/payments/<payment_id>" \
  -H "X-API-Key: change-me-api-key"
```

## How to inspect RabbitMQ and DLQ

- RabbitMQ management UI: `http://localhost:15672`
- Default credentials: `guest/guest`
- Check queues:
  - `payments.new`
  - `payments.new.retry`
  - `payments.new.dlq`

## Quality checks

```bash
make lint
make format
make type-check
make test
```

## Tests

- Unit tests:

```bash
make test-unit
```

- Integration tests:

```bash
make test-integration
```

Covered scenarios include:

- API auth and idempotency
- payment + outbox write integrity
- outbox relay publishing
- gateway behavior
- webhook retry/backoff
- consumer status update and retry/DLQ flow

## Notes and assumptions

- Outbox relay runs inside API process as background task by design to keep compose topology minimal (`postgres`, `rabbitmq`, `api`, `consumer`).
- Consumer retry is explicit (retry queue with TTL and dead-letter back to main exchange), not implicit broker redelivery.
- If webhook fails after retries, processing is treated as retryable at consumer message level and message follows retry/DLQ policy.
