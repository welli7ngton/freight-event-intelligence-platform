from uuid import UUID

from app.application.ports.shipment_repository import (
    ShipmentRepository,
)
from app.domain.shipment.entities import Shipment


class GetShipment:
    def __init__(
        self,
        shipment_repository: ShipmentRepository,
    ):
        self._shipment_repository = shipment_repository

    def execute(
        self,
        shipment_id: UUID,
    ) -> Shipment | None:
        return self._shipment_repository.get(shipment_id)
