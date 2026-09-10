import os
from dataclasses import dataclass
from math import isfinite

from dotenv import load_dotenv

load_dotenv()


def get_required_environment(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value

    raise RuntimeError(
        f"Missing required environment variable: {name}. "
        "Copy .env.example to .env and configure it for this environment."
    )


def get_database_url() -> str:
    return get_required_environment("DATABASE_URL")


def get_rabbitmq_url() -> str:
    return get_required_environment("RABBITMQ_URL")


def get_rabbitmq_exchange() -> str:
    return os.getenv("RABBITMQ_EXCHANGE", "freight.shipment-events")


def get_rabbitmq_queue() -> str:
    return os.getenv("RABBITMQ_QUEUE", "freight.shipment-event-ingestion")


def get_rabbitmq_retry_exchange() -> str:
    return os.getenv("RABBITMQ_RETRY_EXCHANGE", "freight.shipment-events.retry")


def get_rabbitmq_retry_queue() -> str:
    return os.getenv("RABBITMQ_RETRY_QUEUE", "freight.shipment-event-retry")


def get_rabbitmq_dead_letter_exchange() -> str:
    return os.getenv("RABBITMQ_DEAD_LETTER_EXCHANGE", "freight.shipment-events.dlx")


def get_rabbitmq_dead_letter_queue() -> str:
    return os.getenv("RABBITMQ_DEAD_LETTER_QUEUE", "freight.shipment-event-dlq")


def get_rabbitmq_retry_delay_ms() -> int:
    return int(os.getenv("RABBITMQ_RETRY_DELAY_MS", "5000"))


def get_rabbitmq_max_attempts() -> int:
    return int(os.getenv("RABBITMQ_MAX_ATTEMPTS", "3"))


@dataclass(frozen=True)
class OutboxSettings:
    exchange: str
    queue: str
    poll_seconds: float
    retry_seconds: float
    publish_timeout_seconds: float


def get_outbox_settings() -> OutboxSettings:
    def positive(name: str, default: str) -> float:
        value = float(os.getenv(name, default))
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")
        return value

    exchange = os.getenv("OUTBOX_EXCHANGE", "freight.shipment-notifications")
    queue = os.getenv("OUTBOX_QUEUE", "freight.shipment-event-notifications")
    if not exchange or not queue:
        raise ValueError("Outbox exchange and queue must not be empty")
    if exchange in {
        get_rabbitmq_exchange(),
        get_rabbitmq_retry_exchange(),
        get_rabbitmq_dead_letter_exchange(),
    } or queue in {
        get_rabbitmq_queue(),
        get_rabbitmq_retry_queue(),
        get_rabbitmq_dead_letter_queue(),
    }:
        raise ValueError("Outbox topology must be separate from ingestion topology")
    return OutboxSettings(
        exchange=exchange,
        queue=queue,
        poll_seconds=positive("OUTBOX_POLL_SECONDS", "1"),
        retry_seconds=positive("OUTBOX_RETRY_SECONDS", "5"),
        publish_timeout_seconds=positive("OUTBOX_PUBLISH_TIMEOUT_SECONDS", "10"),
    )
