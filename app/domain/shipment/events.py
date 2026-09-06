from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ShipmentEventType(StrEnum):
    SHIPMENT_CREATED = "SHIPMENT_CREATED"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    PICKUP_COMPLETED = "PICKUP_COMPLETED"
    SHIPMENT_DEPARTED = "SHIPMENT_DEPARTED"
    LOCATION_UPDATED = "LOCATION_UPDATED"
    DELAY_DETECTED = "DELAY_DETECTED"
    DELIVERED = "DELIVERED"


# A class to hold a specific property to a single event that does not trigger a transition (LOCATION_UPDATED).
@dataclass(frozen=True, slots=True)
class LocationUpdatedPayload:
    latitude: float
    longitude: float


# An event should never be updated after created.
@dataclass(frozen=True, slots=True)
class ShipmentEvent:
    event_id: UUID
    shipment_id: UUID
    event_type: ShipmentEventType
    source: str
    occurred_at: datetime
    received_at: datetime
    payload: object
