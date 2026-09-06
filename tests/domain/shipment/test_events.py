from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.domain.shipment.events import (
    ShipmentEvent,
    ShipmentEventType,
)


def test_event_is_immutable() -> None:
    now = datetime.now(UTC)

    event = ShipmentEvent(
        event_id=uuid4(),
        shipment_id=uuid4(),
        event_type=ShipmentEventType.DELIVERED,
        source="carrier_api",
        occurred_at=now,
        received_at=now,
        payload={},
    )

    with pytest.raises(FrozenInstanceError):
        event.source = "another_source"
