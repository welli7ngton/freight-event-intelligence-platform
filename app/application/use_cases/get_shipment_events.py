from uuid import UUID

from app.application.ports.shipment_event_repository import (
    ShipmentEventRepository,
)
from app.domain.shipment.events import ShipmentEvent


class GetShipmentEvents:
    def __init__(
        self,
        shipment_event_repository: ShipmentEventRepository,
    ):
        self._shipment_event_repository = shipment_event_repository

    def execute(
        self,
        shipment_id: UUID,
    ) -> list[ShipmentEvent]:
        return self._shipment_event_repository.list_by_shipment(shipment_id)
