from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api.application import app
from app.api.dependencies import get_db
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


@pytest.fixture
def client(db_session: Session):
    def override_get_db():
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_http_flow_persists_and_reads_shipment_events(client) -> None:
    created = client.post(
        "/shipments",
        json={
            "reference_number": "HTTP-POSTGRES-001",
            "origin": "Fortaleza",
            "destination": "Recife",
            "carrier": "Carrier A",
        },
    )

    assert created.status_code == 201
    shipment = created.json()

    fetched = client.get(f"/shipments/{shipment['id']}")
    events = client.get(f"/shipments/{shipment['id']}/events")
    lifecycle_event = client.post(
        "/events",
        json={
            "event_id": str(uuid4()),
            "shipment_id": shipment["id"],
            "event_type": "PICKUP_SCHEDULED",
            "source": "carrier_api",
            "occurred_at": datetime(2026, 9, 7, 12, 0, tzinfo=UTC).isoformat(),
            "payload": {},
        },
    )
    updated = client.get(f"/shipments/{shipment['id']}")

    assert fetched.status_code == 200
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["event_type"] == "SHIPMENT_CREATED"
    assert lifecycle_event.status_code == 200
    assert lifecycle_event.json()["status"] == "SCHEDULED"
    assert updated.status_code == 200
    assert updated.json()["status"] == "SCHEDULED"


def test_http_returns_not_found_for_unknown_shipment(client) -> None:
    response = client.get(f"/shipments/{uuid4()}")

    assert response.status_code == 404


def test_http_retains_late_event_without_regressing_shipment_projection(client) -> None:
    created = client.post(
        "/shipments",
        json={
            "reference_number": "HTTP-OUT-OF-ORDER-001",
            "origin": "Fortaleza",
            "destination": "Recife",
            "carrier": "Carrier A",
        },
    )
    shipment_id = created.json()["id"]
    scheduled_event_id = uuid4()
    late_event_id = uuid4()

    scheduled = client.post(
        "/events",
        json={
            "event_id": str(scheduled_event_id),
            "shipment_id": shipment_id,
            "event_type": "PICKUP_SCHEDULED",
            "source": "carrier_api",
            "occurred_at": datetime(2026, 9, 7, 12, 0, tzinfo=UTC).isoformat(),
            "payload": {},
        },
    )
    late = client.post(
        "/events",
        json={
            "event_id": str(late_event_id),
            "shipment_id": shipment_id,
            "event_type": "PICKUP_COMPLETED",
            "source": "carrier_api",
            "occurred_at": datetime(2026, 9, 7, 11, 55, tzinfo=UTC).isoformat(),
            "payload": {},
        },
    )
    history = client.get(f"/shipments/{shipment_id}/events")

    assert scheduled.status_code == 200
    assert late.status_code == 200
    assert late.json()["status"] == "SCHEDULED"
    by_event_id = {event["event_id"]: event for event in history.json()}
    assert by_event_id[str(scheduled_event_id)]["processing_status"] == "APPLIED"
    assert by_event_id[str(late_event_id)]["processing_status"] == "STORED_OUT_OF_ORDER"
