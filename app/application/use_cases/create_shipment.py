from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.application.messaging.recorded_event_message import RecordedEventMessage
from app.application.ports.outbox_repository import OutboxRepository
from app.application.ports.shipment_event_repository import (
    ShipmentEventRepository,
)
from app.application.ports.shipment_repository import (
    ShipmentRepository,
)
from app.domain.shipment.entities import Shipment
from app.domain.shipment.events import (
    ShipmentEvent,
    ShipmentEventType,
)


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
        shipment_event_repository: ShipmentEventRepository,
        outbox_repository: OutboxRepository,
    ):
        self._shipment_repository = shipment_repository
        self._shipment_event_repository = shipment_event_repository
        self._outbox_repository = outbox_repository

    def execute(
        self,
        input_data: CreateShipmentInput,
    ) -> Shipment:
        created_at = datetime.now(UTC)

        shipment = Shipment.create(
            id=uuid4(),
            reference_number=input_data.reference_number,
            origin=input_data.origin,
            destination=input_data.destination,
            carrier=input_data.carrier,
            created_at=created_at,
        )

        event = ShipmentEvent(
            event_id=uuid4(),
            shipment_id=shipment.id,
            event_type=ShipmentEventType.SHIPMENT_CREATED,
            source="platform",
            occurred_at=created_at,
            received_at=datetime.now(UTC),
            payload={},
        )

        self._shipment_repository.save(shipment)
        self._shipment_event_repository.save(event)
        self._outbox_repository.add(RecordedEventMessage.from_event(event))

        return shipment
