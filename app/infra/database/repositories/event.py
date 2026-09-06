from uuid import UUID

from app.application.ports.shipment_event_repository import (
    ShipmentEventRepository,
)
from app.domain.shipment.events import ShipmentEvent
from app.infra.database.mappers.event_mapper import (
    to_domain,
    to_model,
)
from app.infra.database.models.shipment_event import (
    ShipmentEventModel,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


class SQLAlchemyShipmentEventRepository(ShipmentEventRepository):
    def __init__(self, session: Session):
        self._session = session

    def exists(self, event_id: UUID) -> bool:
        statement = select(ShipmentEventModel.event_id).where(
            ShipmentEventModel.event_id == event_id
        )
        return self._session.scalar(statement) is not None

    def save(self, event: ShipmentEvent) -> None:
        self._session.add(to_model(event))

    def list_by_shipment(
        self,
        shipment_id: UUID,
    ) -> list[ShipmentEvent]:
        statement = (
            select(ShipmentEventModel)
            .where(ShipmentEventModel.shipment_id == shipment_id)
            .order_by(ShipmentEventModel.occurred_at.asc())
        )

        models = self._session.scalars(statement).all()

        return [to_domain(model) for model in models]
