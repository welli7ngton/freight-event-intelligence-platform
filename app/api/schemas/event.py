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
    event_id: UUID = Field(
        description="Unique identifier of the event from the event producer.",
        examples=["7b7d9f8e-2e3c-4f31-9b6a-4f9c4a8e7c10"],
    )
    shipment_id: UUID = Field(
        description="Identifier of the shipment associated with the event.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    event_type: ShipmentEventType = Field(
        description="Event that describes a shipment lifecycle or location change.",
        examples=["LOCATION_UPDATED"],
    )
    source: str = Field(
        min_length=1,
        max_length=100,
        description="System or carrier that produced the event.",
        examples=["carrier-api"],
    )
    occurred_at: datetime = Field(
        description="Time at which the event occurred, in UTC.",
        examples=["2026-09-06T16:40:00Z"],
    )
    payload: dict = Field(
        description=(
            "Event-specific data. LOCATION_UPDATED requires numeric latitude "
            "and longitude fields; other events may use an empty object."
        ),
        examples=[{"latitude": -3.7319, "longitude": -38.5267}],
    )

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

    event_id: UUID = Field(
        description="Unique identifier of the event.",
        examples=["7b7d9f8e-2e3c-4f31-9b6a-4f9c4a8e7c10"],
    )
    shipment_id: UUID = Field(
        description="Identifier of the related shipment.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    event_type: ShipmentEventType = Field(
        description="Type of the recorded shipment event.",
        examples=["LOCATION_UPDATED"],
    )
    source: str = Field(description="Event producer.", examples=["carrier-api"])
    occurred_at: datetime = Field(
        description="Time at which the event occurred, in UTC.",
        examples=["2026-09-06T16:40:00Z"],
    )
    received_at: datetime = Field(
        description="Time at which the API accepted the event, in UTC.",
        examples=["2026-09-06T16:40:02Z"],
    )
    payload: dict = Field(
        description="Event-specific data received from the producer.",
        examples=[{"latitude": -3.7319, "longitude": -38.5267}],
    )
