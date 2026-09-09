from enum import StrEnum

from app.domain.shipment.exceptions import (
    InvalidShipmentEvent,
    InvalidStateTransition,
)
from sqlalchemy.exc import OperationalError


class FailureDisposition(StrEnum):
    RETRY = "RETRY"
    DEAD_LETTER = "DEAD_LETTER"


class ShipmentEventFailureClassifier:
    """Classifies worker failures without placing transport policy in the domain."""

    def classify(self, error: Exception) -> FailureDisposition:
        if isinstance(
            error, InvalidShipmentEvent | InvalidStateTransition | ValueError
        ):
            return FailureDisposition.DEAD_LETTER

        if isinstance(error, OperationalError | OSError | TimeoutError):
            return FailureDisposition.RETRY

        # Unknown failures can be transient. Bound retries ensure they cannot loop.
        return FailureDisposition.RETRY
