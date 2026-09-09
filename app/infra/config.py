import os

from dotenv import load_dotenv

load_dotenv()


def get_required_environment(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value

    raise RuntimeError(
        f"Missing required environment variable: {name}. "
        "Copy .env-example to .env and configure it for this environment."
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
