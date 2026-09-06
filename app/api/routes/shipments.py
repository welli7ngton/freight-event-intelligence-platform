from uuid import UUID

from app.api.dependencies import (
    get_create_shipment_use_case,
    get_get_shipment_events_use_case,
    get_get_shipment_use_case,
)
from app.api.schemas.event import ShipmentEventResponse
from app.api.schemas.shipment import (
    CreateShipmentRequest,
    ShipmentResponse,
)
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.application.use_cases.get_shipment import GetShipment
from app.application.use_cases.get_shipment_events import GetShipmentEvents
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(
    prefix="/shipments",
    tags=["shipments"],
)


@router.post(
    "",
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_shipment(
    request: CreateShipmentRequest,
    use_case: CreateShipment = Depends(get_create_shipment_use_case),
):
    shipment = use_case.execute(
        CreateShipmentInput(
            reference_number=request.reference_number,
            origin=request.origin,
            destination=request.destination,
            carrier=request.carrier,
        )
    )

    return shipment


@router.get(
    "/{shipment_id}",
    response_model=ShipmentResponse,
)
def get_shipment(
    shipment_id: UUID,
    use_case: GetShipment = Depends(get_get_shipment_use_case),
):
    shipment = use_case.execute(shipment_id)

    if shipment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shipment not found",
        )

    return shipment


@router.get(
    "/{shipment_id}/events",
    response_model=list[ShipmentEventResponse],
)
def get_shipment_events(
    shipment_id: UUID,
    use_case: GetShipmentEvents = Depends(get_get_shipment_events_use_case),
):
    return use_case.execute(shipment_id)
