from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.shipment.entities import Shipment
from app.domain.shipment.events import ShipmentEvent, ShipmentEventType
from app.domain.shipment.state_machine import ShipmentStatus


def make_shipment(
    *,
    shipment_id: UUID | None = None,
    reference_number: str = "SHIP-001",
    origin: str = "Fortaleza",
    destination: str = "Sao Paulo",
    carrier: str = "Carrier A",
    status: ShipmentStatus = ShipmentStatus.CREATED,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    current_latitude: float | None = None,
    current_longitude: float | None = None,
    last_location_at: datetime | None = None,
) -> Shipment:
    created_at = created_at or datetime.now(UTC)
    updated_at = updated_at or created_at

    return Shipment(
        id=shipment_id or uuid4(),
        reference_number=reference_number,
        origin=origin,
        destination=destination,
        carrier=carrier,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        current_latitude=current_latitude,
        current_longitude=current_longitude,
        last_location_at=last_location_at,
    )


def make_event(
    *,
    shipment: Shipment,
    event_type: ShipmentEventType = ShipmentEventType.PICKUP_SCHEDULED,
    event_id: UUID | None = None,
    source: str = "test",
    occurred_at: datetime | None = None,
    received_at: datetime | None = None,
    payload: object | None = None,
) -> ShipmentEvent:
    occurred_at = occurred_at or datetime.now(UTC)

    return ShipmentEvent(
        event_id=event_id or uuid4(),
        shipment_id=shipment.id,
        event_type=event_type,
        source=source,
        occurred_at=occurred_at,
        received_at=received_at or occurred_at,
        payload={} if payload is None else payload,
    )
