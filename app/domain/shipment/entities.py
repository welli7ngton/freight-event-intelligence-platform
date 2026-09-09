from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.shipment.events import (
    LocationUpdatedPayload,
    ShipmentEventType,
)
from app.domain.shipment.state_machine import ShipmentStateMachine, ShipmentStatus


@dataclass
class Shipment:
    id: UUID
    reference_number: str
    origin: str
    destination: str
    carrier: str
    status: ShipmentStatus
    created_at: datetime
    updated_at: datetime

    current_latitude: float | None = None
    current_longitude: float | None = None
    last_location_at: datetime | None = None
    last_lifecycle_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        id: UUID,
        reference_number: str,
        origin: str,
        destination: str,
        carrier: str,
        created_at: datetime,
    ) -> "Shipment":
        return cls(
            id=id,
            reference_number=reference_number,
            origin=origin,
            destination=destination,
            carrier=carrier,
            status=ShipmentStatus.CREATED,
            created_at=created_at,
            updated_at=created_at,
        )

    def change_status(
        self,
        event_type: ShipmentEventType,
        occurred_at: datetime,
    ) -> None:
        self.status = ShipmentStateMachine.transition(
            current_state=self.status,
            event_type=event_type,
        )
        self.updated_at = occurred_at
        self.last_lifecycle_at = occurred_at

    def update_location(
        self,
        payload: LocationUpdatedPayload,
        occurred_at: datetime,
    ) -> None:
        self.current_latitude = payload.latitude
        self.current_longitude = payload.longitude
        self.last_location_at = occurred_at
        self.updated_at = occurred_at
