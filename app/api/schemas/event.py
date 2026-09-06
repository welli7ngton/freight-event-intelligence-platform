from datetime import datetime
from uuid import UUID

from app.domain.shipment.events import ShipmentEventType
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class ShipmentEventRequest(BaseModel):
    event_id: UUID
    shipment_id: UUID
    event_type: ShipmentEventType
    source: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    payload: dict

    @model_validator(mode="after")
    def validate_payload(self) -> "ShipmentEventRequest":
        if self.event_type == ShipmentEventType.LOCATION_UPDATED:
            latitude = self.payload.get("latitude")
            longitude = self.payload.get("longitude")

            if not isinstance(latitude, int | float) or isinstance(
                latitude,
                bool,
            ):
                raise ValueError("LOCATION_UPDATED payload requires numeric latitude.")

            if not isinstance(longitude, int | float) or isinstance(
                longitude,
                bool,
            ):
                raise ValueError("LOCATION_UPDATED payload requires numeric longitude.")

        return self


class ShipmentEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    shipment_id: UUID
    event_type: ShipmentEventType
    source: str
    occurred_at: datetime
    received_at: datetime
    payload: dict
