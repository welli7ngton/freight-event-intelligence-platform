from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.api.schemas.event import ShipmentEventRequest
from app.domain.shipment.events import ShipmentEventType
from pydantic import ValidationError


def test_shipment_event_request_accepts_valid_data():
    shipment_id = uuid4()
    event_id = uuid4()
    occurred_at = datetime.now(UTC)

    request = ShipmentEventRequest(
        event_id=event_id,
        shipment_id=shipment_id,
        event_type=ShipmentEventType.LOCATION_UPDATED,
        source="gps",
        occurred_at=occurred_at,
        payload={
            "latitude": -3.7319,
            "longitude": -38.5267,
        },
    )

    assert request.event_id == event_id
    assert request.shipment_id == shipment_id
    assert request.event_type == ShipmentEventType.LOCATION_UPDATED
    assert request.payload["latitude"] == -3.7319


def test_shipment_event_request_rejects_invalid_event_type():
    with pytest.raises(ValidationError):
        ShipmentEventRequest(
            event_id=uuid4(),
            shipment_id=uuid4(),
            event_type="INVALID_EVENT",
            source="gps",
            occurred_at=datetime.now(UTC),
            payload={},
        )
