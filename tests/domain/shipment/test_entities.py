from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import (
    ShipmentEvent,
    ShipmentEventType,
)
from app.domain.shipment.exceptions import InvalidStateTransition
from app.domain.shipment.state_machine import ShipmentStatus
from tests.factories.shipment import make_event


def test_shipment_starts_in_created_state(shipment) -> None:
    assert shipment.status == ShipmentStatus.CREATED


def test_shipment_can_transition_to_scheduled(shipment) -> None:
    occurred_at = datetime.now(UTC)

    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.PICKUP_SCHEDULED,
        occurred_at=occurred_at,
    )

    shipment.change_status(
        event.event_type,
        event.occurred_at,
    )

    assert shipment.status == ShipmentStatus.SCHEDULED
    assert shipment.updated_at == occurred_at


def test_shipment_rejects_invalid_transition(shipment) -> None:
    occurred_at = datetime.now(UTC)

    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.DELIVERED,
        occurred_at=occurred_at,
    )

    with pytest.raises(InvalidStateTransition):
        shipment.change_status(
            event.event_type,
            event.occurred_at,
        )

    assert shipment.status == ShipmentStatus.CREATED


def test_shipment_rejects_event_from_another_shipment(shipment) -> None:
    handler = ShipmentEventHandler()

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
