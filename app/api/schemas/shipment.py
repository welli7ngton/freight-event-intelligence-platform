from datetime import datetime
from uuid import UUID

from app.domain.shipment.entities import ShipmentStatus
from pydantic import BaseModel, ConfigDict, Field


class CreateShipmentRequest(BaseModel):
    reference_number: str = Field(
        min_length=1,
        max_length=100,
        description="Business reference used to identify the shipment.",
        examples=["BR-2026-000184"],
    )
    origin: str = Field(
        min_length=1,
        max_length=255,
        description="Origin city, facility, or logistics hub.",
        examples=["Fortaleza, CE"],
    )
    destination: str = Field(
        min_length=1,
        max_length=255,
        description="Destination city, facility, or logistics hub.",
        examples=["Sao Paulo, SP"],
    )
    carrier: str = Field(
        min_length=1,
        max_length=255,
        description="Carrier or logistics provider responsible for the shipment.",
        examples=["Azul Cargo Express"],
    )


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(
        description="Unique identifier assigned to the shipment.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    reference_number: str = Field(
        description="Business reference used to identify the shipment.",
        examples=["BR-2026-000184"],
    )
    origin: str = Field(description="Shipment origin.", examples=["Fortaleza, CE"])
    destination: str = Field(
        description="Shipment destination.", examples=["Sao Paulo, SP"]
    )
    carrier: str = Field(
        description="Carrier responsible for the shipment.",
        examples=["Azul Cargo Express"],
    )
    status: ShipmentStatus = Field(
        description="Current state in the shipment lifecycle.",
        examples=["IN_TRANSIT"],
    )
    created_at: datetime = Field(
        description="Timestamp when the shipment was created, in UTC.",
        examples=["2026-09-06T14:30:00Z"],
    )
    updated_at: datetime = Field(
        description="Timestamp of the latest shipment update, in UTC.",
        examples=["2026-09-06T16:45:00Z"],
    )
    current_latitude: float | None = Field(
        default=None,
        description="Latest latitude reported by a location event.",
        examples=[-3.7319],
    )
    current_longitude: float | None = Field(
        default=None,
        description="Latest longitude reported by a location event.",
        examples=[-38.5267],
    )
    last_location_at: datetime | None = Field(
        default=None,
        description="Timestamp of the latest location event, in UTC.",
        examples=["2026-09-06T16:40:00Z"],
    )
