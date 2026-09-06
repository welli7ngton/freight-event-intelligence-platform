from datetime import UTC, datetime
from uuid import uuid4

from app.domain.shipment.entities import Shipment
from app.domain.shipment.state_machine import ShipmentStatus
from app.infra.database.mappers.shipment_mapper import (
    to_domain,
    to_model,
)


def test_shipment_mapper_preserves_status_and_location() -> None:
    occurred_at = datetime.now(UTC)
    shipment = Shipment(
        id=uuid4(),
        reference_number="SHIP-001",
        origin="Fortaleza",
        destination="Sao Paulo",
        carrier="Carrier A",
        status=ShipmentStatus.IN_TRANSIT,
        created_at=occurred_at,
        updated_at=occurred_at,
        current_latitude=-3.7319,
        current_longitude=-38.5267,
        last_location_at=occurred_at,
    )

    model = to_model(shipment)
    restored = to_domain(model)

    assert model.status == ShipmentStatus.IN_TRANSIT.value
    assert restored.status is ShipmentStatus.IN_TRANSIT
    assert restored.current_latitude == shipment.current_latitude
    assert restored.current_longitude == shipment.current_longitude
    assert restored.last_location_at == shipment.last_location_at
