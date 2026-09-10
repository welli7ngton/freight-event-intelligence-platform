from collections.abc import Callable

import pika
from app.application.messaging.recorded_event_message import (
    EVENT_RECORDED_ROUTING_KEY,
    RecordedEventMessage,
)


class _DeadlineConnection(pika.SelectConnection):
    def abort(self) -> None:
        # Pika 1.3.2 has no public immediate abort. Isolate the protected API here:
        # close() needs a peer handshake, which cannot bound a stalled publish.
        # _terminate_stream aborts the transport/workflow and invokes close/error.
        if not self.is_closed:
            self._terminate_stream(TimeoutError("Outbound publication deadline"))


class RabbitMQRecordedEventPublisher:
    def __init__(
        self,
        *,
        url: str,
        exchange: str,
        queue: str,
        timeout_seconds: float = 10,
        connection_factory: Callable = _DeadlineConnection,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Publication timeout must be positive")
        self._parameters = pika.URLParameters(url)
        self._parameters.socket_timeout = timeout_seconds
        self._parameters.stack_timeout = timeout_seconds + 1
        self._parameters.blocked_connection_timeout = timeout_seconds
        self._parameters.connection_attempts = 1
        self._exchange = exchange
        self._queue = queue
        self._timeout = timeout_seconds
        self._connection_factory = connection_factory

    def publish(self, message: RecordedEventMessage) -> None:
        _Publication(self, message).run()


class _Publication:
    """One connection/loop per attempt, including a hard publication deadline."""

    def __init__(self, publisher, message) -> None:
        self.publisher = publisher
        self.message = message
        self.error: Exception | None = None
        self.confirmed = False
        self.connection = publisher._connection_factory(
            parameters=publisher._parameters,
            on_open_callback=self.on_open,
            on_open_error_callback=self.on_closed,
            on_close_callback=self.on_closed,
        )

    def run(self) -> None:
        loop = self.connection.ioloop
        loop.call_later(self.publisher._timeout, self.on_deadline)
        try:
            loop.start()
        finally:
            if not self.connection.is_closed:
                self.connection.abort()
                loop.start()  # Drain local transport shutdown, not a peer handshake.
            loop.close()
        if self.error is not None:
            raise self.error
        if not self.confirmed:
            raise RuntimeError("Publication ended without confirmation")

    def on_deadline(self) -> None:
        if not self.confirmed and self.error is None:
            self.error = TimeoutError("Outbound publication deadline")
        self.connection.abort()

    def on_open(self, connection) -> None:
        connection.channel(on_open_callback=self.on_channel)

    def on_channel(self, channel) -> None:
        self.channel = channel
        channel.add_on_close_callback(self.on_channel_closed)
        channel.add_on_return_callback(self.on_returned)
        channel.exchange_declare(
            exchange=self.publisher._exchange,
            exchange_type="topic",
            durable=True,
            callback=self.on_exchange,
        )

    def on_exchange(self, frame) -> None:
        self.channel.queue_declare(
            queue=self.publisher._queue, durable=True, callback=self.on_queue
        )

    def on_queue(self, frame) -> None:
        self.channel.queue_bind(
            queue=self.publisher._queue,
            exchange=self.publisher._exchange,
            routing_key=EVENT_RECORDED_ROUTING_KEY,
            callback=self.on_bound,
        )

    def on_bound(self, frame) -> None:
        self.channel.confirm_delivery(
            ack_nack_callback=self.on_confirmation, callback=self.on_confirm_mode
        )

    def on_confirm_mode(self, frame) -> None:
        self.channel.basic_publish(
            exchange=self.publisher._exchange,
            routing_key=EVENT_RECORDED_ROUTING_KEY,
            body=self.message.body,
            mandatory=True,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=str(self.message.message_id),
                correlation_id=self.message.correlation_id
                or str(self.message.message_id),
                type=EVENT_RECORDED_ROUTING_KEY,
            ),
        )

    def on_returned(self, channel, method, properties, body) -> None:
        self.error = pika.exceptions.UnroutableError([])

    def on_confirmation(self, frame) -> None:
        if isinstance(frame.method, pika.spec.Basic.Ack) and self.error is None:
            self.confirmed = True
        elif self.error is None:
            self.error = pika.exceptions.NackError([])
        self.connection.close()

    def on_channel_closed(self, channel, reason) -> None:
        if not self.confirmed and self.error is None:
            self.error = reason
        if self.connection.is_open:
            self.connection.close()

    def on_closed(self, connection, reason) -> None:
        if not self.confirmed and self.error is None:
            self.error = reason
        connection.ioloop.stop()
