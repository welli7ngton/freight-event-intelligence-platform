from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.domain.shipment.entities import Shipment


class ShipmentRepository(Protocol):
    def get(self, shipment_id: UUID) -> Shipment | None:
        """
        Returns a shipment by its identifier.

        Returns None when the shipment does not exist.
        """
        ...

    def save(self, shipment: Shipment) -> None:
        """
        Persists the current state of a shipment.
        """
        ...
