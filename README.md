# Асинхронный сервис процессинга платежей

Production-like микросервис для тестового задания: принимает запросы на создание платежа, обрабатывает платеж асинхронно через очередь, обновляет статус в БД и отправляет webhook с retry-политикой.

Ключевые цели решения:
- корректная идемпотентность на API и БД-уровне;
- надежная публикация событий через Outbox pattern;
- управляемые retry + DLQ для проблемных сообщений;
- понятный запуск и проверка для ревьюера.

---

## Что реализовано

- `POST /api/v1/payments` (создание платежа, `202 Accepted`)
- `GET /api/v1/payments/{payment_id}` (получение текущего статуса)
- `GET /health` (healthcheck)
- обязательный `X-API-Key` для всех эндпоинтов
- обязательный `Idempotency-Key` для создания платежа
- асинхронный pipeline обработки платежа через RabbitMQ
- consumer с эмуляцией gateway (2-5 секунд, ~90% успех / ~10% ошибка)
- обновление статуса платежа в БД (`pending -> succeeded/failed`)
- отправка webhook с retry и exponential backoff
- Dead Letter Queue для сообщений после исчерпания retry
- Outbox pattern для надежной публикации событий
- миграции Alembic
- Docker / docker-compose окружение
- unit + integration тесты
- OpenAPI/Swagger, линтеры, форматтер, type-check, Makefile-команды

---

## Технологический стек

- **FastAPI** — HTTP API и OpenAPI/Swagger
- **Pydantic v2** — валидация входных/выходных контрактов
- **SQLAlchemy 2.0 async** — работа с БД
- **PostgreSQL** — хранилище платежей и outbox
- **RabbitMQ + FastStream** — брокер и обработка сообщений
- **Alembic** — миграции схемы БД
- **Docker / docker-compose** — локальная инфраструктура и запуск
- **pytest** — unit/integration тестирование
- **ruff / mypy** — lint/format/type-check

---

## Архитектура

### Компоненты

- **API сервис** (`app/main.py`, `app/api/*`)
  - принимает запросы;
  - проверяет `X-API-Key` и `Idempotency-Key`;
  - сохраняет платеж и outbox-событие в одной транзакции.

- **PostgreSQL**
  - таблица `payments` — состояние платежей;
  - таблица `outbox` — события к публикации.

- **Outbox relay** (`app/infrastructure/outbox_relay.py`)
  - периодически читает `outbox`;
  - публикует события в RabbitMQ;
  - помечает событие как `published` только после успешной публикации.

- **RabbitMQ**
  - основной exchange/queue для новых платежей;
  - retry exchange/queue для отложенных повторов;
  - DLX/DLQ для неисправимых сообщений.

- **Consumer** (`app/consumer.py`, `app/application/processor.py`)
  - получает событие `payment.created`;
  - вызывает эмулятор шлюза;
  - обновляет платеж в БД;
  - отправляет webhook;
  - при ошибках применяет retry/DLQ.

### Почему такая архитектура

- разделение API и async-обработки снижает latency ответа клиенту;
- Outbox pattern повышает согласованность между БД и брокером;
- явный retry + DLQ делает систему предсказуемой в эксплуатации;
- идемпотентность снижает риск дублей при ретраях клиентов и сетевых сбоях.

---

## Жизненный цикл платежа

1. Клиент вызывает `POST /api/v1/payments`.
2. API проверяет `X-API-Key` и `Idempotency-Key`.
3. В одной транзакции сохраняются:
   - запись платежа в `payments` со статусом `pending`,
   - событие в `outbox`.
4. Outbox relay публикует событие в RabbitMQ (`payments.new`).
5. Consumer получает сообщение.
6. Выполняется эмуляция внешнего gateway (2-5 сек, ~90/10).
7. Статус платежа обновляется в БД (`succeeded` или `failed`).
8. Отправляется webhook на URL из запроса.
9. Если webhook не доставлен, выполняется retry с backoff.
10. Если retry исчерпан, сообщение переводится в DLQ.

---

## Идемпотентность

### Зачем

Клиент может повторно отправить тот же запрос (таймаут, сетевой сбой, повторный клик). Без идемпотентности это даст дубли платежей.

### Как реализовано

- Заголовок `Idempotency-Key` обязателен для `POST /api/v1/payments`.
- В `payments` есть уникальное ограничение `idempotency_key`.
- Используется upsert (`INSERT ... ON CONFLICT DO NOTHING`), поэтому повторный запрос с тем же ключом возвращает существующий платеж.

### Гарантии

- повтор с тем же ключом не создаёт новый платеж;
- конкурентные одинаковые запросы сходятся к одной записи.

### Ограничения

- ключ должен быть стабильно сформирован клиентом для одного бизнес-действия;
- разные ключи = разные операции.

---

## Outbox pattern

### Проблема, которую решает

Наивный подход: "сначала записали платеж в БД, потом отправили сообщение". Если отправка в брокер упала, БД и очередь расходятся.

### Как работает в проекте

- в транзакции создаются и `payments`, и `outbox`;
- отдельный relay читает `outbox` и публикует в RabbitMQ;
- после успешной публикации событие помечается как `published`.

### Что это дает

- согласованность между состоянием БД и событиями;
- устойчивость к временным сбоям брокера;
- наблюдаемость: видно, какие события еще не опубликованы.

---

## Retry и DLQ

### Что ретраится

- обработка сообщения consumer-ом при retryable ошибках;
- доставка webhook внутри processor (HTTP retry).

### Политика retry для consumer

- при ошибке сообщение републикуется в retry queue;
- используется экспоненциальная задержка (`base * 2^(n-1)`);
- счётчик хранится в `x-retry-count`.

### Когда сообщение уходит в DLQ

- если `x-retry-count` достигает лимита `CONSUMER_RETRY_ATTEMPTS`, сообщение отправляется в `payments.new.dlq`.

### Зачем DLQ

- не блокировать основной поток обработки;
- сохранять "плохие" сообщения для анализа;
- упрощать диагностику и ручной reprocess.

---

## Структура проекта

```text
.
  app/
    api/                # HTTP слой: роуты, зависимости, ошибки
    application/        # бизнес-сценарии (create/process)
    db/                 # ORM модели и session
    domain/             # enums и доменные ошибки
    infrastructure/     # RabbitMQ, outbox relay, репозитории, webhook, retry helper
    consumer.py         # точка входа consumer
    main.py             # точка входа API
  alembic/
    versions/           # миграции
  tests/
    unit/
    integration/
  .env.example
  docker-compose.yml
  Makefile
  pyproject.toml
  README.md
```

---

## Быстрый старт (для ревьюера)

### 1) Подготовка

Проект использует `.env.example` как env-file для `api` и `consumer` в docker-compose.

При необходимости измените `API_KEY` и другие параметры в `.env.example`.

### 2) Запуск

```bash
make up
```

Что поднимется:
- `postgres`
- `rabbitmq`
- `api`
- `consumer`

Миграции применяются автоматически в командах `api` и `consumer`.

### 3) Проверка, что сервис жив

Swagger/OpenAPI:
- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`

Healthcheck:

```bash
curl -X GET "http://localhost:8000/health" \
  -H "X-API-Key: change-me-api-key"
```

### 4) Остановка

```bash
make down
```

---

## Локальная разработка (без запуска API/consumer в контейнерах)

```bash
make install-dev
make migrate
make run-api
# в отдельном терминале
make run-consumer
```

---

## Команды разработки

```bash
make up                # поднять docker-окружение
make down              # остановить и удалить volume
make logs              # смотреть логи

make migrate           # применить миграции

make test              # все тесты
make test-unit         # unit тесты
make test-integration  # integration тесты
make smoke             # быстрый smoke-сценарий

make lint              # ruff check
make format            # ruff format
make type-check        # mypy
make check             # lint + type-check + test
```

---

## Примеры API-запросов

Ниже используйте `API_KEY` из `.env.example`.

### Создать платеж

```bash
curl -X POST "http://localhost:8000/api/v1/payments" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me-api-key" \
  -H "Idempotency-Key: order-123-create" \
  -d '{
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Order #123",
    "metadata": {
      "order_id": "123",
      "customer_id": "abc"
    },
    "webhook_url": "https://merchant.example.com/webhooks/payments"
  }'
```

Пример ответа (`202`):

```json
{
  "payment_id": "7ff44b4b-e78a-4bd9-a2ab-7d0772e80d16",
  "status": "pending",
  "created_at": "2026-03-31T12:00:00Z"
}
```

### Получить платеж

```bash
curl -X GET "http://localhost:8000/api/v1/payments/7ff44b4b-e78a-4bd9-a2ab-7d0772e80d16" \
  -H "X-API-Key: change-me-api-key"
```

Пример ответа (`200`):

```json
{
  "payment_id": "7ff44b4b-e78a-4bd9-a2ab-7d0772e80d16",
  "amount": "1500.00",
  "currency": "RUB",
  "description": "Order #123",
  "metadata": {
    "order_id": "123",
    "customer_id": "abc"
  },
  "status": "succeeded",
  "idempotency_key": "order-123-create",
  "webhook_url": "https://merchant.example.com/webhooks/payments",
  "failure_reason": null,
  "created_at": "2026-03-31T12:00:00Z",
  "processed_at": "2026-03-31T12:00:03Z"
}
```

---

## Тестирование

### Что покрыто

- **Unit**:
  - валидация схем;
  - idempotency в payment service;
  - gateway-эмуляция;
  - webhook retry;
  - outbox relay;
  - retry helper;
  - security dependency;
  - webhook lock;
  - processor idempotency.

- **Integration**:
  - API контракты;
  - auth / idempotency / race-сценарии;
  - consumer retry/DLQ;
  - контракт декларации RabbitMQ topology.

### Запуск

```bash
make test
```

Или выборочно:

```bash
make test-unit
make test-integration
```

---

## Как быстро проверить основной сценарий вручную

1. `make up`
2. Выполнить `POST /api/v1/payments` (пример выше)
3. Скопировать `payment_id` из ответа
4. Вызвать `GET /api/v1/payments/{payment_id}`
5. Посмотреть логи:

```bash
make logs
```

6. Проверить очереди в RabbitMQ UI: `http://localhost:15672`
   - `payments.new`
   - `payments.new.retry`
   - `payments.new.dlq`

---

## Trade-offs и потенциальные улучшения

Что сделано прагматично в рамках тестового задания:
- outbox relay запущен внутри API-процесса (вместо отдельного publisher-сервиса);
- интеграционные тесты ориентированы на контракты и критичные сценарии.

Что логично добавить для production:
- подпись webhook (HMAC) и защита от replay;
- централизованное secrets management;
- полноценные метрики/трейсинг/алерты;
- расширенная observability для outbox/retry/DLQ;
- ручки/утилиты для reprocess DLQ;
- более гибкая retry policy по типам ошибок.

---

## Заключение

Проект реализует полный асинхронный контур обработки платежей с акцентом на надежность: идемпотентность, Outbox pattern, управляемые retry и DLQ.

Для ревью достаточно:
- поднять `make up`,
- создать платеж,
- посмотреть обработку и статус,
- запустить `make check`.

Ключевая логика находится в:
- `app/application/payments.py`
- `app/infrastructure/outbox_relay.py`
- `app/application/processor.py`
- `app/consumer.py`
