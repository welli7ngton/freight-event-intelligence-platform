from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.shipment.entities import Shipment
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import (
    ShipmentEvent,
    ShipmentEventType,
)
from app.domain.shipment.exceptions import InvalidStateTransition
from app.domain.shipment.state_machine import ShipmentStatus


def make_shipment() -> Shipment:
    now = datetime.now(UTC)

    return Shipment.create(
        id=uuid4(),
        reference_number="SHIP-001",
        origin="Fortaleza",
        destination="São Paulo",
        carrier="Carrier A",
        created_at=now,
    )


def make_event(
    shipment: Shipment,
    event_type: ShipmentEventType,
    occurred_at: datetime,
) -> ShipmentEvent:
    return ShipmentEvent(
        event_id=uuid4(),
        shipment_id=shipment.id,
        event_type=event_type,
        source="test",
        occurred_at=occurred_at,
        received_at=occurred_at,
        payload={},
    )


def get_event_handler() -> ShipmentEventHandler:
    return ShipmentEventHandler()


def test_shipment_starts_in_created_state() -> None:
    shipment = make_shipment()

    assert shipment.status == ShipmentStatus.CREATED


def test_shipment_can_transition_to_scheduled() -> None:
    shipment = make_shipment()
    occurred_at = datetime.now(UTC)

    event = make_event(
        shipment,
        ShipmentEventType.PICKUP_SCHEDULED,
        occurred_at,
    )

    shipment.change_status(
        event.event_type,
        event.occurred_at,
    )

    assert shipment.status == ShipmentStatus.SCHEDULED
    assert shipment.updated_at == occurred_at


def test_shipment_rejects_invalid_transition() -> None:
    shipment = make_shipment()
    occurred_at = datetime.now(UTC)

    event = make_event(
        shipment,
        ShipmentEventType.DELIVERED,
        occurred_at,
    )

    with pytest.raises(InvalidStateTransition):
        shipment.change_status(
            event.event_type,
            event.occurred_at,
        )

    assert shipment.status == ShipmentStatus.CREATED


def test_shipment_rejects_event_from_another_shipment() -> None:
    shipment = make_shipment()
    handler = get_event_handler()

    event = ShipmentEvent(
        event_id=uuid4(),
        shipment_id=uuid4(),
        event_type=ShipmentEventType.PICKUP_SCHEDULED,
        source="test",
        occurred_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        payload={},
    )

    with pytest.raises(ValueError):
        handler.handle(shipment, event)
