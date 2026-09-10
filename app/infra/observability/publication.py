import logging
from time import monotonic

from app.application.messaging.recorded_event_message import RecordedEventMessage
from app.application.ports.recorded_event_publisher import RecordedEventPublisher
from app.infra.observability.context import observation_context
from app.infra.observability.logging import observe
from app.infra.observability.metrics import Metrics

logger = logging.getLogger(__name__)


def message_context(message: RecordedEventMessage) -> dict[str, str]:
    return {
        "component": "outbox",
        "correlation_id": message.correlation_id or str(message.message_id),
        "message_id": str(message.message_id),
        "event_id": str(message.event_id),
        "shipment_id": str(message.shipment_id),
    }


class ObservedPublisher:
    def __init__(self, publisher: RecordedEventPublisher, metrics: Metrics) -> None:
        self.publisher, self.metrics = publisher, metrics
        self.message: RecordedEventMessage | None = None

    def publish(self, message: RecordedEventMessage) -> None:
        self.message = message
        started = monotonic()
        outcome, error_type = "broker_confirmed", None
        with observation_context(**message_context(message)):
            try:
                self.publisher.publish(message)
            except BaseException as error:
                outcome, error_type = "publish_failed", type(error).__name__
                raise
            finally:
                elapsed = monotonic() - started
                self.metrics.outbox.labels(outcome).inc()
                self.metrics.outbox_duration.labels(outcome).observe(elapsed)
                observe(
                    logger,
                    "outbox_publish",
                    outcome=outcome,
                    error_type=error_type,
                    duration_seconds=elapsed,
                )
