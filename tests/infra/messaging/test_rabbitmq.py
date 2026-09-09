from datetime import UTC, datetime
from uuid import uuid4

import pika
from app.application.messaging.shipment_event_message import ShipmentEventMessage
from app.domain.shipment.events import ShipmentEventType
from app.domain.shipment.exceptions import InvalidStateTransition
from app.infra.messaging.failure_classifier import (
    FailureDisposition,
    ShipmentEventFailureClassifier,
)
from app.infra.messaging.rabbitmq import (
    RabbitMQShipmentEventConsumer,
    RabbitMQShipmentEventPublisher,
)
from tests.factories.shipment import make_event, make_shipment


class FakeChannel:
    def __init__(self) -> None:
        self.published: list[dict] = []
        self.acknowledged: list[int] = []

    def exchange_declare(self, **kwargs) -> None:
        self.exchange = kwargs

    def basic_publish(self, **kwargs) -> None:
        self.published.append(kwargs)

    def basic_ack(self, *, delivery_tag: int) -> None:
        self.acknowledged.append(delivery_tag)


class FakeConnection:
    def __init__(self) -> None:
        self.channel_instance = FakeChannel()
        self.closed = False

    def channel(self) -> FakeChannel:
        return self.channel_instance

    def close(self) -> None:
        self.closed = True


def make_message() -> ShipmentEventMessage:
    shipment = make_shipment()
    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.PICKUP_SCHEDULED,
        occurred_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
    )
    return ShipmentEventMessage.from_event(message_id=uuid4(), event=event)


def test_publisher_emits_a_durable_versioned_message() -> None:
    connection = FakeConnection()
    publisher = RabbitMQShipmentEventPublisher(
        url="amqp://guest:guest@localhost:5672/%2F",
        exchange="freight.shipment-events",
        connection_factory=lambda parameters: connection,
    )

    publisher.publish(make_message())

    assert connection.closed
    assert connection.channel_instance.published[0]["routing_key"] == (
        "shipment.event.received.v1"
    )
    assert connection.channel_instance.published[0]["properties"].delivery_mode == 2


def test_consumer_acknowledges_after_application_handler_succeeds() -> None:
    message = make_message()
    channel = FakeChannel()
    processed = []
    consumer = RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost:5672/%2F",
        exchange="freight.shipment-events",
        queue="freight.shipment-event-ingestion",
    )

    consumer.process_delivery(
        channel=channel,
        delivery_tag=7,
        body=message.to_json().encode(),
        handle_event=processed.append,
    )

    assert processed[0].event_id == message.event_id
    assert channel.acknowledged == [7]
    assert channel.published == []


def test_consumer_sends_invalid_message_to_the_dead_letter_exchange() -> None:
    channel = FakeChannel()
    consumer = RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost:5672/%2F",
        exchange="freight.shipment-events",
        queue="freight.shipment-event-ingestion",
    )

    consumer.process_delivery(
        channel=channel,
        delivery_tag=9,
        body=b"not-json",
        handle_event=lambda event: None,
    )

    assert channel.acknowledged == [9]
    assert channel.published[0]["exchange"] == "freight.shipment-events.dlx"
    assert channel.published[0]["properties"].headers["x-attempt-count"] == 1
    assert (
        channel.published[0]["properties"].headers["x-last-error-type"] == "ValueError"
    )


def test_consumer_retries_retryable_failure_with_attempt_metadata() -> None:
    channel = FakeChannel()
    consumer = RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost:5672/%2F",
        exchange="freight.shipment-events",
        queue="freight.shipment-event-ingestion",
    )

    consumer.process_delivery(
        channel=channel,
        delivery_tag=11,
        body=make_message().to_json().encode(),
        handle_event=lambda event: (_ for _ in ()).throw(TimeoutError("database")),
    )

    assert channel.acknowledged == [11]
    assert channel.published[0]["exchange"] == "freight.shipment-events.retry"
    assert channel.published[0]["properties"].headers["x-attempt-count"] == 2


def test_consumer_dead_letters_an_exhausted_retryable_failure() -> None:
    channel = FakeChannel()
    consumer = RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost:5672/%2F",
        exchange="freight.shipment-events",
        queue="freight.shipment-event-ingestion",
        max_attempts=3,
    )

    consumer.process_delivery(
        channel=channel,
        delivery_tag=12,
        properties=pika.BasicProperties(headers={"x-attempt-count": 3}),
        body=make_message().to_json().encode(),
        handle_event=lambda event: (_ for _ in ()).throw(TimeoutError("database")),
    )

    assert channel.published[0]["exchange"] == "freight.shipment-events.dlx"


def test_failure_classifier_marks_invalid_transitions_as_permanent() -> None:
    classifier = ShipmentEventFailureClassifier()

    assert (
        classifier.classify(InvalidStateTransition("CREATED", "DELIVERED"))
        is FailureDisposition.DEAD_LETTER
    )
