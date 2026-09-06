from uuid import UUID

from app.application.ports.shipment_repository import ShipmentRepository
from app.domain.shipment.entities import Shipment
from app.infra.database.mappers.shipment_mapper import (
    to_domain,
    to_model,
)
from app.infra.database.models.shipment import ShipmentModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class SQLAlchemyShipmentRepository(ShipmentRepository):
    def __init__(self, session: Session):
        self._session = session

    def get(self, shipment_id: UUID) -> Shipment | None:
        statement = select(ShipmentModel).where(ShipmentModel.id == shipment_id)

        model = self._session.scalar(statement)

        if model is None:
            return None

        return to_domain(model)

    def save(self, shipment: Shipment) -> None:
        model = to_model(shipment)

        existing = self._session.get(ShipmentModel, shipment.id)

        if existing is None:
            self._session.add(model)
            return

        existing.reference_number = model.reference_number
        existing.origin = model.origin
        existing.destination = model.destination
        existing.carrier = model.carrier
        existing.status = model.status
        existing.created_at = model.created_at
        existing.updated_at = model.updated_at

        existing.current_latitude = model.current_latitude
        existing.current_longitude = model.current_longitude
        existing.last_location_at = model.last_location_at
