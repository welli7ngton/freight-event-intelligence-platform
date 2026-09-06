from dataclasses import asdict, is_dataclass
from uuid import UUID

from app.application.ports.shipment_event_repository import (
    ShipmentEventRepository,
)
from app.domain.shipment.events import ShipmentEvent
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
        payload = event.payload
        if is_dataclass(payload):
            payload = asdict(payload)

        model = ShipmentEventModel(
            event_id=event.event_id,
            shipment_id=event.shipment_id,
            event_type=event.event_type,
            source=event.source,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            payload=payload,
        )

        self._session.add(model)

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

        return [
            ShipmentEvent(
                event_id=model.event_id,
                shipment_id=model.shipment_id,
                event_type=model.event_type,
                source=model.source,
                occurred_at=model.occurred_at,
                received_at=model.received_at,
                payload=model.payload,
            )
            for model in models
        ]
