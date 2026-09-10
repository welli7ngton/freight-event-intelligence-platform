import logging
from time import monotonic

from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.infra.config import (
    get_rabbitmq_dead_letter_exchange,
    get_rabbitmq_dead_letter_queue,
    get_rabbitmq_exchange,
    get_rabbitmq_max_attempts,
    get_rabbitmq_queue,
    get_rabbitmq_retry_delay_ms,
    get_rabbitmq_retry_exchange,
    get_rabbitmq_retry_queue,
    get_rabbitmq_url,
)
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.infra.database.session import SessionLocal
from app.infra.messaging.rabbitmq import RabbitMQShipmentEventConsumer
from app.infra.observability.context import current_context
from app.infra.observability.logging import configure_logging, observe
from app.infra.observability.metrics import metrics_server, worker_metrics

logger = logging.getLogger(__name__)


def handle_event(event) -> None:
    started = monotonic()
    with SessionLocal() as session:
        use_case = ReceiveShipmentEvent(
            shipment_repository=SQLAlchemyShipmentRepository(session),
            shipment_event_repository=SQLAlchemyShipmentEventRepository(session),
            event_handler=ShipmentEventHandler(),
            outbox_repository=SQLAlchemyOutboxRepository(session),
            correlation_id=current_context().get("correlation_id"),
        )
        try:
            use_case.execute(event)
            session.commit()
            worker_metrics.ingestion.labels("committed").inc()
            observe(
                logger,
                "ingestion_transaction",
                component="ingestion",
                event_id=str(event.event_id),
                shipment_id=str(event.shipment_id),
                outcome="committed",
                duration_seconds=monotonic() - started,
            )
        except Exception as error:
            session.rollback()
            observe(
                logger,
                "ingestion_transaction",
                component="ingestion",
                event_id=str(event.event_id),
                shipment_id=str(event.shipment_id),
                outcome="rolled_back",
                error_type=type(error).__name__,
                duration_seconds=monotonic() - started,
            )
            raise


def main() -> None:
    configure_logging("ingestion")
    consumer = RabbitMQShipmentEventConsumer(
        url=get_rabbitmq_url(),
        exchange=get_rabbitmq_exchange(),
        queue=get_rabbitmq_queue(),
        retry_exchange=get_rabbitmq_retry_exchange(),
        retry_queue=get_rabbitmq_retry_queue(),
        dead_letter_exchange=get_rabbitmq_dead_letter_exchange(),
        dead_letter_queue=get_rabbitmq_dead_letter_queue(),
        retry_delay_ms=get_rabbitmq_retry_delay_ms(),
        max_attempts=get_rabbitmq_max_attempts(),
    )
    with metrics_server(worker_metrics, "INGESTION_METRICS_PORT", 9101):
        consumer.consume_forever(handle_event)


if __name__ == "__main__":
    main()
