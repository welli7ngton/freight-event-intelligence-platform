from datetime import datetime
from uuid import UUID

from app.domain.shipment.entities import ShipmentStatus
from pydantic import BaseModel, ConfigDict, Field


class CreateShipmentRequest(BaseModel):
    reference_number: str = Field(min_length=1, max_length=100)
    origin: str = Field(min_length=1, max_length=255)
    destination: str = Field(min_length=1, max_length=255)
    carrier: str = Field(min_length=1, max_length=255)


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
