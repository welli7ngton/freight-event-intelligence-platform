class ShipmentDomainError(Exception):
    """Base exception for shipment domain errors."""


class InvalidStateTransition(ShipmentDomainError):
    def __init__(
        self,
        current_state: str,
        event_type: str,
    ) -> None:
        self.current_state = current_state
        self.event_type = event_type

        super().__init__(
            f"Invalid transition from state "
            f"'{current_state}' using event '{event_type}'."
        )


class InvalidShipmentEvent(ShipmentDomainError):
    """Raised when an event is not valid for the shipment event flow."""

    def __init__(self, event_type: str) -> None:
        self.event_type = event_type

        super().__init__(
            f"Event type '{event_type}' cannot be received through the event flow."
        )
