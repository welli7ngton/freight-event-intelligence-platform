from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import (
    LocationUpdatedPayload,
    ShipmentEvent,
    ShipmentEventProcessingStatus,
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


def test_late_location_event_is_retained_without_regressing_current_location(
    shipment,
) -> None:
    handler = ShipmentEventHandler()
    latest_at = datetime(2026, 9, 8, 10, 5, tzinfo=UTC)
    handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.LOCATION_UPDATED,
            occurred_at=latest_at,
            payload=LocationUpdatedPayload(latitude=-3.73, longitude=-38.52),
        ),
    )

    status = handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.LOCATION_UPDATED,
            occurred_at=datetime(2026, 9, 8, 9, 55, tzinfo=UTC),
            payload=LocationUpdatedPayload(latitude=-23.55, longitude=-46.63),
        ),
    )

    assert status is ShipmentEventProcessingStatus.STORED_OUT_OF_ORDER
    assert shipment.current_latitude == -3.73
    assert shipment.current_longitude == -38.52
    assert shipment.last_location_at == latest_at


def test_late_lifecycle_event_is_retained_without_changing_status(shipment) -> None:
    handler = ShipmentEventHandler()
    handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.PICKUP_SCHEDULED,
            occurred_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        ),
    )

    status = handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.PICKUP_COMPLETED,
            occurred_at=datetime(2026, 9, 8, 9, 55, tzinfo=UTC),
        ),
    )

    assert status is ShipmentEventProcessingStatus.STORED_OUT_OF_ORDER
    assert shipment.status is ShipmentStatus.SCHEDULED


def test_lifecycle_event_is_not_blocked_by_a_newer_location_event(shipment) -> None:
    handler = ShipmentEventHandler()
    handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.PICKUP_SCHEDULED,
            occurred_at=datetime(2026, 9, 8, 10, 0, tzinfo=UTC),
        ),
    )
    handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.LOCATION_UPDATED,
            occurred_at=datetime(2026, 9, 8, 10, 10, tzinfo=UTC),
            payload=LocationUpdatedPayload(latitude=-3.73, longitude=-38.52),
        ),
    )

    status = handler.handle(
        shipment,
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.PICKUP_COMPLETED,
            occurred_at=datetime(2026, 9, 8, 10, 5, tzinfo=UTC),
        ),
    )

    assert status is ShipmentEventProcessingStatus.APPLIED
    assert shipment.status is ShipmentStatus.PICKED_UP
