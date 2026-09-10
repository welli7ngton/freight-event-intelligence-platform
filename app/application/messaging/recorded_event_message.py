import json
from dataclasses import asdict, dataclass, is_dataclass
from uuid import UUID, uuid4

from app.domain.shipment.events import ShipmentEvent

EVENT_RECORDED_ROUTING_KEY = "shipment.event.recorded.v1"


@dataclass(frozen=True, slots=True)
class RecordedEventMessage:
    """A snapshot of a recorded fact, never an ingestion command."""

    message_id: UUID
    event_id: UUID
    shipment_id: UUID
    body: str
    correlation_id: str | None = None

    @classmethod
    def from_event(
        cls, event: ShipmentEvent, *, correlation_id: str | None = None
    ) -> "RecordedEventMessage":
        message_id = uuid4()
        payload = (
            asdict(event.payload) if is_dataclass(event.payload) else event.payload
        )
        if not isinstance(payload, dict):
            raise ValueError("Recorded-event payload must be an object")
        envelope = {
            "contract_version": "v1",
            "message_type": EVENT_RECORDED_ROUTING_KEY,
            "message_id": str(message_id),
            "event_id": str(event.event_id),
            "shipment_id": str(event.shipment_id),
            "event_type": event.event_type.value,
            "source": event.source,
            "occurred_at": event.occurred_at.isoformat(),
            "received_at": event.received_at.isoformat(),
            "payload": payload,
            "processing_status": event.processing_status.value,
        }
        return cls(
            message_id=message_id,
            event_id=event.event_id,
            shipment_id=event.shipment_id,
            body=json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            correlation_id=correlation_id,
        )
