from datetime import datetime
from uuid import UUID

from app.application.messaging.recorded_event_message import RecordedEventMessage
from app.domain.shipment.entities import Shipment
from app.domain.shipment.events import ShipmentEvent


class InMemoryShipmentRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Shipment] = {}

    @property
    def shipments(self) -> dict[UUID, Shipment]:
        return self.items

    def get(self, shipment_id: UUID) -> Shipment | None:
        return self.items.get(shipment_id)

    def save(self, shipment: Shipment) -> None:
        self.items[shipment.id] = shipment


class InMemoryShipmentEventRepository:
    def __init__(self) -> None:
        self.items: list[ShipmentEvent] = []

    @property
    def events(self) -> dict[UUID, ShipmentEvent]:
        return {event.event_id: event for event in self.items}

    def exists(self, event_id: UUID) -> bool:
        return any(event.event_id == event_id for event in self.items)

    def save(self, event: ShipmentEvent) -> None:
        self.items.append(event)

    def list_by_shipment(self, shipment_id: UUID) -> list[ShipmentEvent]:
        return sorted(
            (event for event in self.items if event.shipment_id == shipment_id),
            key=lambda event: event.occurred_at,
        )


class InMemoryOutboxRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, RecordedEventMessage] = {}
        self.published: dict[UUID, datetime] = {}
        self.failures: dict[UUID, tuple[datetime, str]] = {}

    def add(self, message: RecordedEventMessage) -> None:
        self.items[message.message_id] = message

    def claim_next(self, now: datetime) -> RecordedEventMessage | None:
        return next(
            (
                message
                for key, message in self.items.items()
                if key not in self.published
                and (key not in self.failures or self.failures[key][0] <= now)
            ),
            None,
        )

    def mark_published(self, message_id: UUID, now: datetime) -> None:
        self.published[message_id] = now

    def mark_failed(self, message_id: UUID, *, retry_at: datetime, error: str) -> None:
        self.failures[message_id] = (retry_at, error)
