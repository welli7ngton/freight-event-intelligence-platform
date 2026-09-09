from datetime import UTC, datetime

from app.api.dependencies import get_db, get_receive_shipment_event_use_case
from app.api.schemas.errors import ErrorResponse
from app.api.schemas.event import ShipmentEventRequest
from app.api.schemas.shipment import ShipmentResponse
from app.application.use_cases.receive_shipment_events import (
    ReceiveShipmentEvent,
)
from app.domain.shipment.events import ShipmentEvent
from app.domain.shipment.exceptions import (
    InvalidShipmentEvent,
    InvalidStateTransition,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/events",
    tags=["events"],
)


@router.post(
    "",
    summary="Receive a shipment event",
    description="""
    Accepts an event emitted by a carrier or operational system, persists it,
    and applies the corresponding shipment state or location update.

    `LOCATION_UPDATED` events must include numeric `latitude` and `longitude`
    values in `payload`. Other event types may send an empty object.
    """,
    response_model=ShipmentResponse,
    status_code=status.HTTP_200_OK,
    response_description="The shipment after applying the event.",
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "The event references a shipment that does not exist.",
            "model": ErrorResponse,
        },
        status.HTTP_409_CONFLICT: {
            "description": "The event is not valid for the shipment's current state.",
            "model": ErrorResponse,
        },
    },
)
def receive_event(
    request: ShipmentEventRequest,
    use_case: ReceiveShipmentEvent = Depends(get_receive_shipment_event_use_case),
    db: Session = Depends(get_db),
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
        shipment = use_case.execute(event)
        # The unique event-id constraint is the concurrent idempotency guard.
        # Flushing exposes a collision while this route can still roll back and
        # return the canonical persisted shipment to the duplicate caller.
        db.flush()
        return shipment
    except IntegrityError as error:
        db.rollback()

        if not _is_duplicate_event_id(error):
            raise

        shipment = use_case.get_current_shipment(event.shipment_id)
        if shipment is None:
            raise
        return shipment
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
    except InvalidShipmentEvent as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


def _is_duplicate_event_id(error: IntegrityError) -> bool:
    """Return whether PostgreSQL rejected the shipment event identity key."""
    diagnostic = getattr(error.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None) == "shipment_events_pkey"
