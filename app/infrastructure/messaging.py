"""RabbitMQ topology and FastStream broker wiring."""

from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue
from faststream.rabbit.schemas.constants import ExchangeType

from app.config import get_settings

settings = get_settings()
payments_routing_key = settings.payments_routing_key

broker = RabbitBroker(settings.rabbitmq_url)

payments_exchange = RabbitExchange(
    name=settings.payments_exchange,
    type=ExchangeType.DIRECT,
    durable=True,
    declare=True,
)

retry_exchange = RabbitExchange(
    name=settings.payments_retry_exchange,
    type=ExchangeType.DIRECT,
    durable=True,
    declare=True,
)

dead_letter_exchange = RabbitExchange(
    name=settings.payments_dlx_exchange,
    type=ExchangeType.DIRECT,
    durable=True,
    declare=True,
)

payments_queue = RabbitQueue(
    name=settings.payments_queue,
    durable=True,
    routing_key=payments_routing_key,
    arguments={
        "x-dead-letter-exchange": settings.payments_dlx_exchange,
    },
)

payments_retry_queue = RabbitQueue(
    name=settings.payments_retry_queue,
    durable=True,
    routing_key=payments_routing_key,
    arguments={
        "x-dead-letter-exchange": settings.payments_exchange,
    },
)

payments_dlq = RabbitQueue(
    name=settings.payments_dlq,
    durable=True,
    routing_key=payments_routing_key,
)


async def setup_rabbitmq_topology() -> None:
    """Declare exchanges/queues and required bindings idempotently."""

    declared_payments_exchange = await broker.declare_exchange(payments_exchange)
    declared_retry_exchange = await broker.declare_exchange(retry_exchange)
    declared_dead_letter_exchange = await broker.declare_exchange(dead_letter_exchange)
    declared_main_queue = await broker.declare_queue(payments_queue)
    declared_retry_queue = await broker.declare_queue(payments_retry_queue)
    declared_dlq = await broker.declare_queue(payments_dlq)
    await declared_main_queue.bind(declared_payments_exchange, routing_key=payments_routing_key)
    await declared_retry_queue.bind(declared_retry_exchange, routing_key=payments_routing_key)
    await declared_dlq.bind(declared_dead_letter_exchange, routing_key=payments_routing_key)


async def connect_and_setup_topology() -> None:
    """Ensure broker connection is open and topology exists."""

    await broker.connect()
    await setup_rabbitmq_topology()
