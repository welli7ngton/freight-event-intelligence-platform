import pytest
from app.domain.shipment.events import ShipmentEventType
from app.domain.shipment.exceptions import InvalidStateTransition
from app.domain.shipment.state_machine import (
    ShipmentStateMachine,
    ShipmentStatus,
)


@pytest.mark.parametrize(
    ("current_state", "event_type", "expected_state"),
    [
        (
            ShipmentStatus.CREATED,
            ShipmentEventType.PICKUP_SCHEDULED,
            ShipmentStatus.SCHEDULED,
        ),
        (
            ShipmentStatus.SCHEDULED,
            ShipmentEventType.PICKUP_COMPLETED,
            ShipmentStatus.PICKED_UP,
        ),
        (
            ShipmentStatus.IN_TRANSIT,
            ShipmentEventType.DELAY_DETECTED,
            ShipmentStatus.DELAYED,
        ),
        (
            ShipmentStatus.IN_TRANSIT,
            ShipmentEventType.DELIVERED,
            ShipmentStatus.DELIVERED,
        ),
        (
            ShipmentStatus.DELAYED,
            ShipmentEventType.DELIVERED,
            ShipmentStatus.DELIVERED,
        ),
    ],
)
def test_valid_transitions(
    current_state: ShipmentStatus,
    event_type: ShipmentEventType,
    expected_state: ShipmentStatus,
) -> None:
    result = ShipmentStateMachine.transition(
        current_state=current_state,
        event_type=event_type,
    )

    assert result == expected_state


@pytest.mark.parametrize(
    ("current_state", "event_type"),
    [
        (
            ShipmentStatus.CREATED,
            ShipmentEventType.DELIVERED,
        ),
        (
            ShipmentStatus.CREATED,
            ShipmentEventType.DELAY_DETECTED,
        ),
        (
            ShipmentStatus.SCHEDULED,
            ShipmentEventType.DELIVERED,
        ),
        (
            ShipmentStatus.PICKED_UP,
            ShipmentEventType.DELIVERED,
        ),
        (
            ShipmentStatus.DELIVERED,
            ShipmentEventType.LOCATION_UPDATED,
        ),
        (
            ShipmentStatus.DELIVERED,
            ShipmentEventType.DELIVERED,
        ),
    ],
)
def test_invalid_transitions_raise_exception(
    current_state: ShipmentStatus,
    event_type: ShipmentEventType,
) -> None:
    with pytest.raises(InvalidStateTransition):
        ShipmentStateMachine.transition(
            current_state=current_state,
            event_type=event_type,
        )
