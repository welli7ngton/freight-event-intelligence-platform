from datetime import UTC, datetime

from app.api.dependencies import get_receive_shipment_event_use_case
from app.api.schemas.event import ShipmentEventRequest
from app.api.schemas.shipment import ShipmentResponse
from app.application.use_cases.receive_shipment_events import (
    ReceiveShipmentEvent,
)
from app.domain.shipment.events import ShipmentEvent
from app.domain.shipment.exceptions import InvalidStateTransition
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(
    prefix="/events",
    tags=["events"],
)


@router.post(
    "",
    response_model=ShipmentResponse,
    status_code=status.HTTP_200_OK,
)
def receive_event(
    request: ShipmentEventRequest,
    use_case: ReceiveShipmentEvent = Depends(get_receive_shipment_event_use_case),
):
    event = ShipmentEvent(
        event_id=request.event_id,
        shipment_id=request.shipment_id,
        event_type=request.event_type,
        source=request.source,
        occurred_at=request.occurred_at,
        received_at=datetime.now(UTC),
        payload=request.payload,
    )

    try:
        return use_case.execute(event)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except InvalidStateTransition as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
