from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.application.use_cases.receive_shipment_events import (
    ReceiveShipmentEvent,
)
from app.domain.shipment.entities import Shipment
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import ShipmentEvent, ShipmentEventType


class InMemoryShipmentRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Shipment] = {}

    def get(self, shipment_id: UUID) -> Shipment | None:
        return self.items.get(shipment_id)

    def save(self, shipment: Shipment) -> None:
        self.items[shipment.id] = shipment


class InMemoryShipmentEventRepository:
    def __init__(self) -> None:
        self.items: list[ShipmentEvent] = []

    def save(self, event: ShipmentEvent) -> None:
        self.items.append(event)

    def exists(self, event_id: UUID) -> bool:
        return any(event.event_id == event_id for event in self.items)

    def list_by_shipment(
        self,
        shipment_id: UUID,
    ) -> list[ShipmentEvent]:
        return [event for event in self.items if event.shipment_id == shipment_id]


def test_create_shipment_generates_identity_and_timestamps() -> None:
    repository = InMemoryShipmentRepository()
    use_case = CreateShipment(repository)

    shipment = use_case.execute(
        CreateShipmentInput(
            reference_number="SHIP-001",
            origin="Fortaleza",
            destination="Sao Paulo",
            carrier="Carrier A",
        )
    )

    assert shipment.id in repository.items
    assert shipment.status.value == "CREATED"
    assert shipment.created_at.tzinfo == UTC
    assert shipment.updated_at == shipment.created_at


def test_receive_shipment_event_updates_and_persists_shipment() -> None:
    shipment_repository = InMemoryShipmentRepository()
    event_repository = InMemoryShipmentEventRepository()
    shipment = Shipment.create(
        id=uuid4(),
        reference_number="SHIP-001",
        origin="Fortaleza",
        destination="Sao Paulo",
        carrier="Carrier A",
        created_at=datetime.now(UTC),
    )
    shipment_repository.save(shipment)
    occurred_at = datetime.now(UTC)
    event = ShipmentEvent(
        event_id=uuid4(),
        shipment_id=shipment.id,
        event_type=ShipmentEventType.PICKUP_SCHEDULED,
        source="test",
        occurred_at=occurred_at,
        received_at=datetime.now(UTC),
        payload={},
    )

    result = ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        event_handler=ShipmentEventHandler(),
    ).execute(event)

    assert result.status.value == "SCHEDULED"
    assert result.updated_at == occurred_at
    assert event_repository.items == [event]
    assert shipment_repository.get(shipment.id) is result


def test_receive_shipment_event_is_idempotent() -> None:
    shipment_repository = InMemoryShipmentRepository()
    event_repository = InMemoryShipmentEventRepository()
    shipment = Shipment.create(
        id=uuid4(),
        reference_number="SHIP-001",
        origin="Fortaleza",
        destination="Sao Paulo",
        carrier="Carrier A",
        created_at=datetime.now(UTC),
    )
    shipment_repository.save(shipment)
    event = ShipmentEvent(
        event_id=uuid4(),
        shipment_id=shipment.id,
        event_type=ShipmentEventType.PICKUP_SCHEDULED,
        source="test",
        occurred_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        payload={},
    )
    use_case = ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        event_handler=ShipmentEventHandler(),
    )

    first_result = use_case.execute(event)
    second_result = use_case.execute(event)

    assert first_result.status.value == "SCHEDULED"
    assert second_result.status.value == "SCHEDULED"
    assert event_repository.items == [event]
