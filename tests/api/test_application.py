from datetime import UTC, datetime
from uuid import uuid4

from app.api.application import app
from app.api.dependencies import get_receive_shipment_event_use_case
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.domain.shipment.events import ShipmentEventType
from sqlalchemy.exc import IntegrityError
from tests.factories.repositories import InMemoryOutboxRepository
from tests.factories.shipment import make_shipment


def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_shipment_returns_created_shipment(client):
    response = client.post(
        "/shipments",
        json={
            "reference_number": "SHIP-001",
            "origin": "Fortaleza",
            "destination": "São Paulo",
            "carrier": "Carrier A",
        },
    )

    assert response.status_code == 201

    body = response.json()

    assert body["reference_number"] == "SHIP-001"
    assert body["origin"] == "Fortaleza"
    assert body["destination"] == "São Paulo"
    assert body["carrier"] == "Carrier A"
    assert body["status"] == "CREATED"


def test_get_shipment_returns_persisted_shipment(client):
    create_response = client.post(
        "/shipments",
        json={
            "reference_number": "SHIP-002",
            "origin": "Fortaleza",
            "destination": "Recife",
            "carrier": "Carrier B",
        },
    )

    shipment_id = create_response.json()["id"]

    response = client.get(f"/shipments/{shipment_id}")

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == shipment_id
    assert body["reference_number"] == "SHIP-002"


def test_get_unknown_shipment_returns_not_found(client):
    shipment_id = uuid4()

    response = client.get(f"/shipments/{shipment_id}")

    assert response.status_code == 404


def test_receive_event_updates_shipment(client):
    create_response = client.post(
        "/shipments",
        json={
            "reference_number": "SHIP-003",
            "origin": "Fortaleza",
            "destination": "Recife",
            "carrier": "Carrier C",
        },
    )

    shipment_id = create_response.json()["id"]

    event_time = datetime.now(UTC)

    event_response = client.post(
        "/events",
        json={
            "event_id": str(uuid4()),
            "shipment_id": shipment_id,
            "event_type": "PICKUP_SCHEDULED",
            "source": "carrier-api",
            "occurred_at": event_time.isoformat(),
            "payload": {},
        },
    )

    assert event_response.status_code == 200

    body = event_response.json()

    assert body["id"] == shipment_id
    assert body["status"] == "SCHEDULED"


def test_get_shipment_events_returns_event_history(client):
    create_response = client.post(
        "/shipments",
        json={
            "reference_number": "SHIP-004",
            "origin": "Fortaleza",
            "destination": "Recife",
            "carrier": "Carrier D",
        },
    )

    shipment_id = create_response.json()["id"]

    event_id = uuid4()

    client.post(
        "/events",
        json={
            "event_id": str(event_id),
            "shipment_id": shipment_id,
            "event_type": "PICKUP_SCHEDULED",
            "source": "carrier-api",
            "occurred_at": datetime.now(UTC).isoformat(),
            "payload": {},
        },
    )

    response = client.get(f"/shipments/{shipment_id}/events")

    assert response.status_code == 200

    body = response.json()

    # Assert body length is 2 because on the creation of the shipment is triggered a SHIPMENT_CREATED event
    assert len(body) == 2
    assert body[1]["event_id"] == str(event_id)
    assert body[1]["shipment_id"] == shipment_id


def test_receive_event_for_unknown_shipment_returns_not_found(client):
    response = client.post(
        "/events",
        json={
            "event_id": str(uuid4()),
            "shipment_id": str(uuid4()),
            "event_type": "PICKUP_SCHEDULED",
            "source": "carrier-api",
            "occurred_at": datetime.now(UTC).isoformat(),
            "payload": {},
        },
    )

    assert response.status_code == 404


def test_concurrent_duplicate_event_returns_the_persisted_shipment(client):
    shipment = make_shipment()

    class Diagnostic:
        constraint_name = "shipment_events_pkey"

    class DuplicateEventError(Exception):
        diag = Diagnostic()

    class ConflictingUseCase:
        def execute(self, event):
            raise IntegrityError("INSERT", {}, DuplicateEventError())

        def get_current_shipment(self, shipment_id):
            assert shipment_id == shipment.id
            return shipment

    original_override = app.dependency_overrides[get_receive_shipment_event_use_case]
    app.dependency_overrides[get_receive_shipment_event_use_case] = (
        lambda: ConflictingUseCase()
    )
    try:
        response = client.post(
            "/events",
            json={
                "event_id": str(uuid4()),
                "shipment_id": str(shipment.id),
                "event_type": "PICKUP_SCHEDULED",
                "source": "carrier-api",
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": {},
            },
        )
    finally:
        app.dependency_overrides[get_receive_shipment_event_use_case] = (
            original_override
        )

    assert response.status_code == 200
    assert response.json()["id"] == str(shipment.id)


def test_create_shipment_generates_identity_timestamps_and_creation_event(
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

    assert len(event_repository.items) == 1

    event = event_repository.items[0]

    assert event.event_type == ShipmentEventType.SHIPMENT_CREATED
    assert event.shipment_id == shipment.id
    assert event.occurred_at == shipment.created_at
    assert event.source == "platform"
    assert event.payload == {}
