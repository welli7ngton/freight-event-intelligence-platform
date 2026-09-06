from dataclasses import asdict, is_dataclass

from app.domain.shipment.events import ShipmentEvent, ShipmentEventType
from app.infra.database.models import ShipmentEventModel


def to_domain(model: ShipmentEventModel) -> ShipmentEvent:
    return ShipmentEvent(
        event_id=model.event_id,
        shipment_id=model.shipment_id,
        event_type=ShipmentEventType(model.event_type),
        source=model.source,
        occurred_at=model.occurred_at,
        received_at=model.received_at,
        payload=model.payload,
    )


def to_model(event: ShipmentEvent) -> ShipmentEventModel:
    payload = event.payload
    if is_dataclass(payload):
        payload = asdict(payload)

    return ShipmentEventModel(
        event_id=event.event_id,
        shipment_id=event.shipment_id,
        event_type=event.event_type.value,
        source=event.source,
        occurred_at=event.occurred_at,
        received_at=event.received_at,
        payload=payload,
    )


__all__ = ["to_domain", "to_model"]
