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
- Message flow is bounded and deterministic:
  - original delivery has `x-retry-count=0`;
  - failed attempts are republished with `x-retry-count=1..3`;
  - when `x-retry-count` reaches configured max (`CONSUMER_RETRY_ATTEMPTS`), message is moved to DLQ;
  - no infinite requeue loops are used.

### Idempotency policy

- `Idempotency-Key` is mandatory for payment creation.
- `payments.idempotency_key` has unique constraint.
- Creation uses `INSERT ... ON CONFLICT DO NOTHING` and returns existing payment if duplicate key is used.
- Parallel identical requests return the same payment and do not create duplicate outbox messages.
- Consumer-side duplicate deliveries are also controlled for webhook side effects by lock-based webhook coordination in DB.

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

Compose uses `.env.example` directly as env file for `api` and `consumer`.

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Application name for metadata/health |
| `APP_VERSION` | Application version for metadata/health |
| `ENVIRONMENT` | Runtime environment marker (`local/dev/test/prod`) |
| `DEBUG` | Debug logging mode |
| `API_HOST` | API bind host |
| `API_PORT` | API bind port |
| `API_KEY` | Static API key required on all endpoints |
| `DATABASE_URL` | SQLAlchemy async DB URL |
| `RABBITMQ_URL` | RabbitMQ broker URL |
| `PAYMENTS_EXCHANGE` | Main exchange for payment-created events |
| `PAYMENTS_ROUTING_KEY` | Routing key for payment events |
| `PAYMENTS_QUEUE` | Main consumer queue (`payments.new`) |
| `PAYMENTS_RETRY_EXCHANGE` | Retry exchange |
| `PAYMENTS_RETRY_QUEUE` | Retry queue |
| `PAYMENTS_DLX_EXCHANGE` | Dead-letter exchange |
| `PAYMENTS_DLQ` | Dead-letter queue |
| `ENABLE_BROKER_STARTUP` | Enables broker connection on API startup |
| `ENABLE_OUTBOX_RELAY` | Enables outbox relay background loop in API |
| `CONSUMER_RETRY_ATTEMPTS` | Max message retry count before DLQ |
| `CONSUMER_RETRY_BASE_DELAY_SECONDS` | Base delay for consumer retry backoff |
| `OUTBOX_POLL_INTERVAL_SECONDS` | Relay polling interval |
| `OUTBOX_BATCH_SIZE` | Relay batch size |
| `OUTBOX_LOCK_TTL_SECONDS` | Outbox lock timeout for stuck messages |
| `WEBHOOK_TIMEOUT_SECONDS` | Per-request webhook timeout |
| `WEBHOOK_RETRY_ATTEMPTS` | Webhook retry attempts |
| `WEBHOOK_RETRY_BASE_DELAY_SECONDS` | Base delay for webhook retry backoff |
| `WEBHOOK_LOCK_TTL_SECONDS` | TTL for webhook-side effect lock in DB |
| `GATEWAY_SLEEP_MIN_SECONDS` | Gateway emulator min delay |
| `GATEWAY_SLEEP_MAX_SECONDS` | Gateway emulator max delay |
| `GATEWAY_SUCCESS_RATE` | Gateway success probability |

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

1. Review and adjust `.env.example` values (especially `API_KEY`) if needed.

```bash
vim .env.example
```

2. Start all services:

```bash
make up
```

3. Check API docs:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

4. Stop services:

```bash
make down
```

## API examples

Use the same API key as configured in `.env.example`.

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
- RabbitMQ topology declaration contract (exchange/queue/binding wiring)
- API-key dependency behavior and health endpoint contract

## Notes and assumptions

- Outbox relay runs inside API process as background task by design to keep compose topology minimal (`postgres`, `rabbitmq`, `api`, `consumer`).
- Consumer retry is explicit (retry queue with TTL and dead-letter back to main exchange), not implicit broker redelivery.
- If webhook fails after retries, processing is treated as retryable at consumer message level and message follows retry/DLQ policy.
- Webhook delivery is guarded by a DB lock (`webhook_lock_id` / `webhook_locked_at`) so duplicate message deliveries do not trigger duplicate webhook side effects.
