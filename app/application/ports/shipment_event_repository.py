from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.shipment.events import ShipmentEvent


class ShipmentEventRepository(Protocol):
    def exists(self, event_id: UUID) -> bool:
        """Returns whether an event has already been persisted."""
        ...

    def save(self, event: ShipmentEvent) -> None:
        """
        Persists a shipment event.
        """
        ...

    def list_by_shipment(
        self,
        shipment_id: UUID,
    ) -> list[ShipmentEvent]:
        """
        Returns all events associated with a shipment.
        """
        ...
