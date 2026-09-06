from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.application.ports.shipment_repository import (
    ShipmentRepository,
)
from app.domain.shipment.entities import Shipment


@dataclass(frozen=True)
class CreateShipmentInput:
    reference_number: str
    origin: str
    destination: str
    carrier: str


class CreateShipment:
    def __init__(
        self,
        shipment_repository: ShipmentRepository,
    ):
        self._shipment_repository = shipment_repository

    def execute(
        self,
        input_data: CreateShipmentInput,
    ) -> Shipment:
        shipment = Shipment.create(
            id=uuid4(),
            reference_number=input_data.reference_number,
            origin=input_data.origin,
            destination=input_data.destination,
            carrier=input_data.carrier,
            created_at=datetime.now(UTC),
        )

        self._shipment_repository.save(shipment)

        return shipment
