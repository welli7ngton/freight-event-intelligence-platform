import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from uuid import UUID

from app.domain.shipment.events import (
    ShipmentEvent,
    ShipmentEventProcessingStatus,
    ShipmentEventType,
)

CONTRACT_VERSION = "v1"
EVENT_RECEIVED_ROUTING_KEY = "shipment.event.received.v1"


@dataclass(frozen=True, slots=True)
class ShipmentEventMessage:
    """Broker-neutral representation of an operational shipment event."""

    message_id: UUID
    event_id: UUID
    shipment_id: UUID
    event_type: ShipmentEventType
    source: str
    occurred_at: datetime
    received_at: datetime
    payload: dict
    contract_version: str = CONTRACT_VERSION

    @classmethod
    def from_event(
        cls, *, message_id: UUID, event: ShipmentEvent
    ) -> "ShipmentEventMessage":
        payload = event.payload
        if is_dataclass(payload):
            payload = asdict(payload)
        if not isinstance(payload, dict):
            raise ValueError("Shipment-event message payload must be an object.")

        return cls(
            message_id=message_id,
            event_id=event.event_id,
            shipment_id=event.shipment_id,
            event_type=event.event_type,
            source=event.source,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            payload=payload,
        )

    def to_event(self) -> ShipmentEvent:
        return ShipmentEvent(
            event_id=self.event_id,
            shipment_id=self.shipment_id,
            event_type=self.event_type,
            source=self.source,
            occurred_at=self.occurred_at,
            received_at=self.received_at,
            payload=self.payload,
            processing_status=ShipmentEventProcessingStatus.APPLIED,
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "contract_version": self.contract_version,
                "message_id": str(self.message_id),
                "event_id": str(self.event_id),
                "shipment_id": str(self.shipment_id),
                "event_type": self.event_type.value,
                "source": self.source,
                "occurred_at": self.occurred_at.isoformat(),
                "received_at": self.received_at.isoformat(),
                "payload": self.payload,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, body: bytes | str) -> "ShipmentEventMessage":
        try:
            data = json.loads(body)
            if data["contract_version"] != CONTRACT_VERSION:
                raise ValueError("Unsupported shipment-event message contract version.")
            if not isinstance(data["payload"], dict):
                raise ValueError("Shipment-event message payload must be an object.")
            return cls(
                contract_version=data["contract_version"],
                message_id=UUID(data["message_id"]),
                event_id=UUID(data["event_id"]),
                shipment_id=UUID(data["shipment_id"]),
                event_type=ShipmentEventType(data["event_type"]),
                source=data["source"],
                occurred_at=datetime.fromisoformat(data["occurred_at"]),
                received_at=datetime.fromisoformat(data["received_at"]),
                payload=data["payload"],
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Invalid shipment-event message.") from error
