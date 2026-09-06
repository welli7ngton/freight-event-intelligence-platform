from uuid import UUID

from app.api.dependencies import (
    get_create_shipment_use_case,
    get_get_shipment_events_use_case,
    get_get_shipment_use_case,
)
from app.api.schemas.errors import ErrorResponse
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
from fastapi import APIRouter, Depends, HTTPException, Path, status

router = APIRouter(
    prefix="/shipments",
    tags=["shipments"],
)


@router.post(
    "",
    summary="Create a shipment",
    description="""
    Creates a shipment in the `CREATED` state and records its initial
    `SHIPMENT_CREATED` event atomically.
    """,
    response_model=ShipmentResponse,
    status_code=status.HTTP_201_CREATED,
    response_description="The newly created shipment.",
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
    summary="Get a shipment",
    description="Returns the current details and lifecycle status of a shipment.",
    response_model=ShipmentResponse,
    response_description="The requested shipment.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "No shipment exists with the supplied identifier.",
            "model": ErrorResponse,
        },
    },
)
def get_shipment(
    shipment_id: UUID = Path(
        description="Unique identifier of the shipment to retrieve.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
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
    summary="List shipment events",
    description="Returns the event history for a shipment ordered by occurrence time.",
    response_model=list[ShipmentEventResponse],
    response_description="The shipment event history, oldest event first.",
)
def get_shipment_events(
    shipment_id: UUID = Path(
        description="Unique identifier of the shipment whose events are requested.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    use_case: GetShipmentEvents = Depends(get_get_shipment_events_use_case),
):
    return use_case.execute(shipment_id)
