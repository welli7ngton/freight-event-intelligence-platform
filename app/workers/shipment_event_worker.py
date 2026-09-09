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
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.infra.database.session import SessionLocal
from app.infra.messaging.rabbitmq import RabbitMQShipmentEventConsumer


def handle_event(event) -> None:
    with SessionLocal() as session:
        use_case = ReceiveShipmentEvent(
            shipment_repository=SQLAlchemyShipmentRepository(session),
            shipment_event_repository=SQLAlchemyShipmentEventRepository(session),
            event_handler=ShipmentEventHandler(),
        )
        try:
            use_case.execute(event)
        except Exception:
            session.rollback()
            raise
        else:
            session.commit()


def main() -> None:
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
    consumer.consume_forever(handle_event)


if __name__ == "__main__":
    main()
