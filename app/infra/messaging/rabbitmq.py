from collections.abc import Callable
from datetime import UTC, datetime

import pika
from app.application.messaging.shipment_event_message import (
    EVENT_RECEIVED_ROUTING_KEY,
    ShipmentEventMessage,
)
from app.application.ports.shipment_event_publisher import ShipmentEventPublisher
from app.domain.shipment.events import ShipmentEvent
from app.infra.messaging.failure_classifier import (
    FailureDisposition,
    ShipmentEventFailureClassifier,
)

RETRY_ROUTING_KEY = "shipment.event.retry.v1"
DEAD_LETTER_ROUTING_KEY = "shipment.event.dead-letter.v1"


class RabbitMQShipmentEventPublisher(ShipmentEventPublisher):
    """Publishes durable, versioned messages to a RabbitMQ topic exchange."""

    def __init__(
        self,
        *,
        url: str,
        exchange: str,
        connection_factory: Callable = pika.BlockingConnection,
    ) -> None:
        self._parameters = pika.URLParameters(url)
        self._exchange = exchange
        self._connection_factory = connection_factory

    def publish(self, message: ShipmentEventMessage) -> None:
        connection = self._connection_factory(self._parameters)
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self._exchange,
                exchange_type="topic",
                durable=True,
            )
            channel.basic_publish(
                exchange=self._exchange,
                routing_key=EVENT_RECEIVED_ROUTING_KEY,
                body=message.to_json(),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=pika.DeliveryMode.Persistent,
                    message_id=str(message.message_id),
                    type=EVENT_RECEIVED_ROUTING_KEY,
                ),
            )
        finally:
            connection.close()


class RabbitMQShipmentEventConsumer:
    """Consumes operational events and delegates processing to the use case."""

    def __init__(
        self,
        *,
        url: str,
        exchange: str,
        queue: str,
        retry_exchange: str = "freight.shipment-events.retry",
        retry_queue: str = "freight.shipment-event-retry",
        dead_letter_exchange: str = "freight.shipment-events.dlx",
        dead_letter_queue: str = "freight.shipment-event-dlq",
        retry_delay_ms: int = 5000,
        max_attempts: int = 3,
        failure_classifier: ShipmentEventFailureClassifier | None = None,
    ) -> None:
        self._parameters = pika.URLParameters(url)
        self._exchange = exchange
        self._queue = queue
        self._retry_exchange = retry_exchange
        self._retry_queue = retry_queue
        self._dead_letter_exchange = dead_letter_exchange
        self._dead_letter_queue = dead_letter_queue
        self._retry_delay_ms = retry_delay_ms
        self._max_attempts = max_attempts
        self._failure_classifier = (
            failure_classifier or ShipmentEventFailureClassifier()
        )

    def consume_forever(self, handle_event: Callable[[ShipmentEvent], None]) -> None:
        connection = pika.BlockingConnection(self._parameters)
        channel = connection.channel()
        self.declare_topology(channel)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(
            queue=self._queue,
            on_message_callback=lambda channel,
            method,
            properties,
            body: self.process_delivery(
                channel=channel,
                delivery_tag=method.delivery_tag,
                properties=properties,
                body=body,
                handle_event=handle_event,
            ),
        )
        try:
            channel.start_consuming()
        finally:
            connection.close()

    def declare_topology(self, channel) -> None:
        channel.exchange_declare(
            exchange=self._exchange,
            exchange_type="topic",
            durable=True,
        )
        channel.exchange_declare(
            exchange=self._retry_exchange,
            exchange_type="topic",
            durable=True,
        )
        channel.exchange_declare(
            exchange=self._dead_letter_exchange,
            exchange_type="topic",
            durable=True,
        )
        channel.queue_declare(queue=self._queue, durable=True)
        channel.queue_bind(
            exchange=self._exchange,
            queue=self._queue,
            routing_key=EVENT_RECEIVED_ROUTING_KEY,
        )
        channel.queue_declare(
            queue=self._retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": self._retry_delay_ms,
                "x-dead-letter-exchange": self._exchange,
                "x-dead-letter-routing-key": EVENT_RECEIVED_ROUTING_KEY,
            },
        )
        channel.queue_bind(
            exchange=self._retry_exchange,
            queue=self._retry_queue,
            routing_key=RETRY_ROUTING_KEY,
        )
        channel.queue_declare(queue=self._dead_letter_queue, durable=True)
        channel.queue_bind(
            exchange=self._dead_letter_exchange,
            queue=self._dead_letter_queue,
            routing_key=DEAD_LETTER_ROUTING_KEY,
        )

    def process_delivery(
        self,
        *,
        channel,
        delivery_tag: int,
        body: bytes,
        handle_event: Callable[[ShipmentEvent], None],
        properties: pika.BasicProperties | None = None,
    ) -> None:
        try:
            message = ShipmentEventMessage.from_json(body)
            handle_event(message.to_event())
        except Exception as error:
            self._handle_failure(
                channel=channel,
                delivery_tag=delivery_tag,
                properties=properties,
                body=body,
                error=error,
            )
            return

        channel.basic_ack(delivery_tag=delivery_tag)

    def _handle_failure(
        self,
        *,
        channel,
        delivery_tag: int,
        properties: pika.BasicProperties | None,
        body: bytes,
        error: Exception,
    ) -> None:
        headers = dict(properties.headers or {}) if properties else {}
        attempt_count = int(headers.get("x-attempt-count", 1))
        headers.update(
            {
                "x-attempt-count": attempt_count,
                "x-first-failed-at": headers.get(
                    "x-first-failed-at",
                    datetime.now(UTC).isoformat(),
                ),
                "x-last-error-type": type(error).__name__,
                "x-last-error-message": str(error)[:500],
            }
        )
        retryable = self._failure_classifier.classify(error) is FailureDisposition.RETRY

        if retryable and attempt_count < self._max_attempts:
            headers["x-attempt-count"] = attempt_count + 1
            exchange = self._retry_exchange
            routing_key = RETRY_ROUTING_KEY
        else:
            exchange = self._dead_letter_exchange
            routing_key = DEAD_LETTER_ROUTING_KEY

        channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=self._failure_properties(properties, headers),
        )
        channel.basic_ack(delivery_tag=delivery_tag)

    @staticmethod
    def _failure_properties(
        original: pika.BasicProperties | None,
        headers: dict,
    ) -> pika.BasicProperties:
        return pika.BasicProperties(
            content_type=(original.content_type if original else "application/json"),
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=original.message_id if original else None,
            type=original.type if original else EVENT_RECEIVED_ROUTING_KEY,
            headers=headers,
        )
