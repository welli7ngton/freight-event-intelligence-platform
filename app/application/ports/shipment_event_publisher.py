from typing import Protocol

from app.application.messaging.shipment_event_message import ShipmentEventMessage


class ShipmentEventPublisher(Protocol):
    """Publishes a broker-neutral shipment event message."""

    def publish(self, message: ShipmentEventMessage) -> None: ...
