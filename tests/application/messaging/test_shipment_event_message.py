from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.application.messaging.shipment_event_message import ShipmentEventMessage
from app.domain.shipment.events import LocationUpdatedPayload, ShipmentEventType
from tests.factories.shipment import make_event, make_shipment


def test_message_serialization_is_deterministic_and_round_trips() -> None:
    shipment = make_shipment()
    event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.LOCATION_UPDATED,
        occurred_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
        payload=LocationUpdatedPayload(latitude=-3.73, longitude=-38.52),
    )
    message = ShipmentEventMessage.from_event(message_id=uuid4(), event=event)

    serialized = message.to_json()
    restored = ShipmentEventMessage.from_json(serialized)

    assert serialized == message.to_json()
    assert restored == message
    assert restored.to_event().payload == {"latitude": -3.73, "longitude": -38.52}


def test_message_rejects_an_unknown_contract_version() -> None:
    with pytest.raises(ValueError, match="Invalid shipment-event message"):
        ShipmentEventMessage.from_json(
            '{"contract_version":"v2","message_id":"not-a-uuid"}'
        )
