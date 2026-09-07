from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.domain.shipment.events import LocationUpdatedPayload, ShipmentEventType
from app.domain.shipment.state_machine import ShipmentStatus
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from tests.factories.shipment import make_event, make_shipment

pytestmark = pytest.mark.integration


def test_shipment_repository_round_trips_all_persisted_state(db_session) -> None:
    occurred_at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    shipment = make_shipment(
        reference_number="SHIP-POSTGRES-001",
        status=ShipmentStatus.IN_TRANSIT,
        created_at=occurred_at,
        updated_at=occurred_at + timedelta(minutes=5),
        current_latitude=-3.7319,
        current_longitude=-38.5267,
        last_location_at=occurred_at + timedelta(minutes=5),
    )
    repository = SQLAlchemyShipmentRepository(db_session)

    repository.save(shipment)
    db_session.commit()

    restored = repository.get(shipment.id)

    assert restored == shipment


def test_shipment_repository_returns_none_for_unknown_shipment(db_session) -> None:
    repository = SQLAlchemyShipmentRepository(db_session)

    assert repository.get(uuid4()) is None


def test_event_repository_persists_orders_and_reconstructs_location_payload(
    db_session,
) -> None:
    shipment = make_shipment(reference_number="SHIP-POSTGRES-002")
    shipment_repository = SQLAlchemyShipmentRepository(db_session)
    event_repository = SQLAlchemyShipmentEventRepository(db_session)
    first_occurred_at = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    second_occurred_at = first_occurred_at + timedelta(minutes=5)
    later_event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.LOCATION_UPDATED,
        occurred_at=second_occurred_at,
        received_at=second_occurred_at + timedelta(seconds=10),
        payload=LocationUpdatedPayload(latitude=-3.7319, longitude=-38.5267),
    )
    earlier_event = make_event(
        shipment=shipment,
        occurred_at=first_occurred_at,
        received_at=first_occurred_at + timedelta(seconds=10),
        payload={"checkpoint": "origin"},
    )

    shipment_repository.save(shipment)
    event_repository.save(later_event)
    event_repository.save(earlier_event)
    db_session.commit()

    events = event_repository.list_by_shipment(shipment.id)

    assert [event.event_id for event in events] == [
        earlier_event.event_id,
        later_event.event_id,
    ]
    assert events[1].occurred_at == later_event.occurred_at
    assert events[1].received_at == later_event.received_at
    assert events[1].payload == {"latitude": -3.7319, "longitude": -38.5267}
    assert event_repository.exists(later_event.event_id)
    assert not event_repository.exists(uuid4())
