from enum import StrEnum

from app.domain.shipment.events import ShipmentEventType
from app.domain.shipment.exceptions import InvalidStateTransition


class ShipmentStatus(StrEnum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    DELAYED = "DELAYED"
    DELIVERED = "DELIVERED"


class ShipmentStateMachine:
    _TRANSITIONS: dict[
        ShipmentStatus,
        dict[ShipmentEventType, ShipmentStatus],
    ] = {
        ShipmentStatus.CREATED: {
            ShipmentEventType.PICKUP_SCHEDULED: ShipmentStatus.SCHEDULED,
        },
        ShipmentStatus.SCHEDULED: {
            ShipmentEventType.PICKUP_COMPLETED: ShipmentStatus.PICKED_UP,
        },
        ShipmentStatus.PICKED_UP: {
            ShipmentEventType.SHIPMENT_DEPARTED: ShipmentStatus.IN_TRANSIT,
        },
        ShipmentStatus.IN_TRANSIT: {
            ShipmentEventType.DELAY_DETECTED: ShipmentStatus.DELAYED,
            ShipmentEventType.DELIVERED: ShipmentStatus.DELIVERED,
        },
        ShipmentStatus.DELAYED: {
            ShipmentEventType.SHIPMENT_DEPARTED: ShipmentStatus.IN_TRANSIT,
            ShipmentEventType.DELIVERED: ShipmentStatus.DELIVERED,
        },
    }

    @classmethod
    def transition(
        cls,
        current_state: ShipmentStatus,
        event_type: ShipmentEventType,
    ) -> ShipmentStatus:
        transitions = cls._TRANSITIONS.get(current_state, {})

        next_state = transitions.get(event_type)

        if next_state is None:
            raise InvalidStateTransition(
                current_state=current_state.value,
                event_type=event_type.value,
            )

        return next_state
