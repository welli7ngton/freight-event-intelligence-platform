from datetime import UTC, datetime

import pytest
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.application.use_cases.receive_shipment_events import (
    ReceiveShipmentEvent,
)
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import ShipmentEventProcessingStatus, ShipmentEventType
from app.domain.shipment.exceptions import InvalidShipmentEvent
from app.domain.shipment.state_machine import ShipmentStatus
from tests.factories.repositories import InMemoryOutboxRepository
from tests.factories.shipment import make_event, make_shipment


def test_create_shipment_generates_identity_and_timestamps(
    in_memory_repositories,
) -> None:
    shipment_repository, shipment_event_repository = in_memory_repositories
    use_case = CreateShipment(
        shipment_repository, shipment_event_repository, InMemoryOutboxRepository()
    )

    shipment = use_case.execute(
        CreateShipmentInput(
            reference_number="SHIP-001",
            origin="Fortaleza",
            destination="Sao Paulo",
            carrier="Carrier A",
        )
    )

    assert shipment.id in shipment_repository.items
    assert shipment.status.value == "CREATED"
    assert shipment.created_at.tzinfo == UTC
    assert shipment.updated_at == shipment.created_at


def test_receive_shipment_event_updates_and_persists_shipment(
    in_memory_repositories,
) -> None:
    shipment_repository, event_repository = in_memory_repositories
    shipment = make_shipment()
    shipment_repository.save(shipment)
    occurred_at = datetime.now(UTC)
    event = make_event(shipment=shipment, occurred_at=occurred_at)

    result = ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        outbox_repository=InMemoryOutboxRepository(),
        event_handler=ShipmentEventHandler(),
    ).execute(event)

    assert result.status.value == "SCHEDULED"
    assert result.updated_at == occurred_at
    assert event_repository.items == [event]
    assert shipment_repository.get(shipment.id) is result


def test_receive_shipment_event_is_idempotent(in_memory_repositories) -> None:
    shipment_repository, event_repository = in_memory_repositories
    shipment = make_shipment()
    shipment_repository.save(shipment)
    event = make_event(shipment=shipment)
    use_case = ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        outbox_repository=InMemoryOutboxRepository(),
        event_handler=ShipmentEventHandler(),
    )

    first_result = use_case.execute(event)
    second_result = use_case.execute(event)

    assert first_result.status.value == "SCHEDULED"
    assert second_result.status.value == "SCHEDULED"
    assert event_repository.items == [event]


def test_receive_late_event_persists_history_without_changing_projection(
    in_memory_repositories,
) -> None:
    shipment_repository, event_repository = in_memory_repositories
    shipment = make_shipment()
    shipment_repository.save(shipment)
    use_case = ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        outbox_repository=InMemoryOutboxRepository(),
        event_handler=ShipmentEventHandler(),
    )
    use_case.execute(
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.PICKUP_SCHEDULED,
            occurred_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        )
    )
    late_event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.PICKUP_COMPLETED,
        occurred_at=datetime(2026, 9, 8, 9, 55, tzinfo=UTC),
    )

    result = use_case.execute(late_event)

    assert result.status is ShipmentStatus.SCHEDULED
    assert event_repository.items[-1].event_id == late_event.event_id
    assert (
        event_repository.items[-1].processing_status
        is ShipmentEventProcessingStatus.STORED_OUT_OF_ORDER
    )


def test_receive_shipment_created_event_is_rejected_before_processing(
    in_memory_repositories,
) -> None:
    shipment = make_shipment()
    shipment_repository, event_repository = in_memory_repositories
    handler = ShipmentEventHandler()

    use_case = ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        outbox_repository=InMemoryOutboxRepository(),
        event_handler=handler,
    )

    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.SHIPMENT_CREATED,
    )

    with pytest.raises(InvalidShipmentEvent):
        use_case.execute(event)

    assert shipment.status == ShipmentStatus.CREATED
    assert event_repository.items == []


def test_event_handler_rejects_shipment_created_as_a_state_transition():
    shipment = make_shipment()
    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.SHIPMENT_CREATED,
    )

    with pytest.raises(InvalidShipmentEvent):
        ShipmentEventHandler().handle(shipment, event)

    assert shipment.status == ShipmentStatus.CREATED


def test_create_shipment_persists_shipment_and_creation_event(
    in_memory_repositories,
) -> None:
    shipment_repository, event_repository = in_memory_repositories
    use_case = CreateShipment(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        outbox_repository=InMemoryOutboxRepository(),
    )

    shipment = use_case.execute(
        CreateShipmentInput(
            reference_number="REF-001",
            origin="Fortaleza",
            destination="Recife",
            carrier="Carrier A",
        )
    )

    assert shipment.status == ShipmentStatus.CREATED
    assert shipment_repository.get(shipment.id) == shipment
    assert len(event_repository.items) == 1

    event = event_repository.items[0]

    assert event.event_type == ShipmentEventType.SHIPMENT_CREATED
    assert event.shipment_id == shipment.id
    assert event.occurred_at == shipment.created_at
    assert event.received_at >= event.occurred_at
