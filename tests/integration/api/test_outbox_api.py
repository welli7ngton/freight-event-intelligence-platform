from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from app.api import dependencies
from app.api.application import app
from app.api.dependencies import get_event_handler
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.infra.database.models.outbox_event import OutboxEventModel
from app.infra.database.models.shipment_event import ShipmentEventModel
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.integration


@pytest.fixture
def outbox_client(db_session, integration_engine, monkeypatch):
    factory = sessionmaker(integration_engine, expire_on_commit=False, autoflush=False)

    monkeypatch.setattr(dependencies, "SessionLocal", factory)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def create(client):
    response = client.post(
        "/shipments",
        json={
            "reference_number": "OUTBOX-HTTP",
            "origin": "Fortaleza",
            "destination": "Recife",
            "carrier": "Carrier A",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def event_body(shipment_id):
    return {
        "event_id": str(uuid4()),
        "shipment_id": shipment_id,
        "event_type": "PICKUP_SCHEDULED",
        "source": "carrier",
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": {},
    }


def test_real_concurrent_http_duplicate_has_one_event_and_intent(
    outbox_client, integration_engine
):
    shipment_id = create(outbox_client)
    barrier = Barrier(2)

    class ConcurrentHandler(ShipmentEventHandler):
        def handle(self, shipment, event):
            barrier.wait(timeout=10)
            return super().handle(shipment, event)

    app.dependency_overrides[get_event_handler] = ConcurrentHandler
    body = event_body(shipment_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: outbox_client.post("/events", json=body), range(2))
        )
    assert [r.status_code for r in responses] == [200, 200]
    assert all(r.json()["status"] == "SCHEDULED" for r in responses)
    with Session(integration_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ShipmentEventModel)
                .where(ShipmentEventModel.event_id == body["event_id"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.event_id == body["event_id"])
            )
            == 1
        )


def test_http_late_duplicate_and_invalid_notification_outcomes(
    outbox_client, integration_engine, monkeypatch
):
    # HTTP must never contact the broker, even when the configured endpoint is down.
    monkeypatch.setenv("RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:1/%2F")
    shipment_id = create(outbox_client)
    body = event_body(shipment_id)
    assert outbox_client.post("/events", json=body).status_code == 200
    assert outbox_client.post("/events", json=body).status_code == 200
    late = {
        **body,
        "event_id": str(uuid4()),
        "event_type": "PICKUP_COMPLETED",
        "occurred_at": (
            datetime.fromisoformat(body["occurred_at"]) - timedelta(minutes=1)
        ).isoformat(),
    }
    assert outbox_client.post("/events", json=late).status_code == 200
    invalid = {**body, "event_id": str(uuid4()), "event_type": "SHIPMENT_CREATED"}
    assert outbox_client.post("/events", json=invalid).status_code == 422
    with Session(integration_engine) as session:
        rows = session.scalars(select(OutboxEventModel)).all()
        assert len(rows) == 3
        late_row = next(row for row in rows if str(row.event_id) == late["event_id"])
        assert late_row.payload["processing_status"] == "STORED_OUT_OF_ORDER"
        assert all(row.published_at is None for row in rows)
