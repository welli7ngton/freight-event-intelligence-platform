from app.application.ports.shipment_event_repository import (
    ShipmentEventRepository,
)
from app.application.ports.shipment_repository import (
    ShipmentRepository,
)
from app.domain.shipment.entities import Shipment
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import ShipmentEvent, ShipmentEventType
from app.domain.shipment.exceptions import InvalidShipmentEvent


class ReceiveShipmentEvent:
    def __init__(
        self,
        shipment_repository: ShipmentRepository,
        shipment_event_repository: ShipmentEventRepository,
        event_handler: ShipmentEventHandler,
    ):
        self._shipment_repository = shipment_repository
        self._shipment_event_repository = shipment_event_repository
        self._event_handler = event_handler

    def execute(
        self,
        event: ShipmentEvent,
    ) -> Shipment:
        if event.event_type == ShipmentEventType.SHIPMENT_CREATED:
            raise InvalidShipmentEvent(event.event_type.value)

        shipment = self._shipment_repository.get(event.shipment_id)

        if shipment is None:
            raise ValueError(f"Shipment {event.shipment_id} not found.")

        if self._shipment_event_repository.exists(event.event_id):
            return shipment

        self._event_handler.handle(
            shipment,
            event,
        )

        self._shipment_event_repository.save(event)
        self._shipment_repository.save(shipment)

        return shipment
