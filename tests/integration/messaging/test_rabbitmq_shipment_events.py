from datetime import UTC, datetime
from uuid import uuid4

import pika
import pytest
from app.application.messaging.shipment_event_message import EVENT_RECEIVED_ROUTING_KEY
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import ShipmentEventType
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.infra.messaging.rabbitmq import (
    RabbitMQShipmentEventConsumer,
    RabbitMQShipmentEventPublisher,
)
from tests.factories.shipment import make_event, make_shipment

pytestmark = pytest.mark.integration


def test_rabbitmq_message_reaches_receive_shipment_event_use_case(
    db_session,
    rabbitmq_url: str,
) -> None:
    shipment = make_shipment(reference_number="RABBITMQ-INGESTION-001")
    shipment_repository = SQLAlchemyShipmentRepository(db_session)
    event_repository = SQLAlchemyShipmentEventRepository(db_session)
    shipment_repository.save(shipment)
    db_session.commit()
    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.PICKUP_SCHEDULED,
        occurred_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
    )
    queue = f"freight-test-{uuid4()}"
    exchange = "freight.shipment-events-test"
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
    channel.queue_declare(queue=queue, exclusive=True, auto_delete=True)
    channel.queue_bind(
        exchange=exchange,
        queue=queue,
        routing_key=EVENT_RECEIVED_ROUTING_KEY,
    )

    try:
        publisher = RabbitMQShipmentEventPublisher(
            url=rabbitmq_url,
            exchange=exchange,
        )
        publisher.publish(message=publisher_message(event))
        method, _, body = channel.basic_get(queue=queue, auto_ack=False)
        assert method is not None

        use_case = ReceiveShipmentEvent(
            shipment_repository=shipment_repository,
            shipment_event_repository=event_repository,
            outbox_repository=SQLAlchemyOutboxRepository(db_session),
            event_handler=ShipmentEventHandler(),
        )
        consumer = RabbitMQShipmentEventConsumer(
            url=rabbitmq_url,
            exchange=exchange,
            queue=queue,
        )
        consumer.process_delivery(
            channel=channel,
            delivery_tag=method.delivery_tag,
            body=body,
            handle_event=use_case.execute,
        )
        db_session.commit()

        assert event_repository.exists(event.event_id)
    finally:
        connection.close()


def publisher_message(event):
    from app.application.messaging.shipment_event_message import ShipmentEventMessage

    return ShipmentEventMessage.from_event(message_id=uuid4(), event=event)


def test_invalid_rabbitmq_message_is_preserved_in_dead_letter_queue(
    rabbitmq_url: str,
) -> None:
    suffix = uuid4().hex
    exchange = f"freight-test-{suffix}"
    queue = f"freight-main-{suffix}"
    retry_exchange = f"freight-retry-{suffix}"
    retry_queue = f"freight-retry-queue-{suffix}"
    dead_letter_exchange = f"freight-dlx-{suffix}"
    dead_letter_queue = f"freight-dlq-{suffix}"
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    consumer = RabbitMQShipmentEventConsumer(
        url=rabbitmq_url,
        exchange=exchange,
        queue=queue,
        retry_exchange=retry_exchange,
        retry_queue=retry_queue,
        dead_letter_exchange=dead_letter_exchange,
        dead_letter_queue=dead_letter_queue,
        retry_delay_ms=10,
        max_attempts=2,
    )
    consumer.declare_topology(channel)
    body = b"invalid-shipment-event"
    channel.basic_publish(
        exchange=exchange,
        routing_key=EVENT_RECEIVED_ROUTING_KEY,
        body=body,
        properties=pika.BasicProperties(content_type="application/json"),
    )

    try:
        method, properties, delivered_body = channel.basic_get(
            queue=queue, auto_ack=False
        )
        assert method is not None
        consumer.process_delivery(
            channel=channel,
            delivery_tag=method.delivery_tag,
            properties=properties,
            body=delivered_body,
            handle_event=lambda event: None,
        )
        _, dlq_properties, dlq_body = channel.basic_get(
            queue=dead_letter_queue,
            auto_ack=True,
        )

        assert dlq_body == body
        assert dlq_properties.headers["x-attempt-count"] == 1
        assert dlq_properties.headers["x-last-error-type"] == "ValueError"
    finally:
        connection.close()
