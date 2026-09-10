import json
from datetime import UTC, datetime
from uuid import UUID

from app.application.messaging.recorded_event_message import (
    EVENT_RECORDED_ROUTING_KEY,
    RecordedEventMessage,
)
from app.infra.database.models.outbox_event import OutboxEventModel
from app.infra.database.models.shipment import ShipmentModel
from app.infra.database.models.shipment_event import ShipmentEventModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class SQLAlchemyOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, message: RecordedEventMessage) -> None:
        # Flush parent writes before adding their dependent outbox row. No commit:
        # any later error still rolls back the whole business operation. Event PK
        # races surface before the outbox unique constraint, preserving HTTP recovery.
        shipments = [
            model for model in self._session.new if isinstance(model, ShipmentModel)
        ]
        if shipments:
            self._session.flush(shipments)
        events = [
            model
            for model in self._session.new
            if isinstance(model, ShipmentEventModel)
        ]
        if events:
            self._session.flush(events)
        now = datetime.now(UTC)
        self._session.add(
            OutboxEventModel(
                id=message.message_id,
                event_id=message.event_id,
                shipment_id=message.shipment_id,
                message_type=EVENT_RECORDED_ROUTING_KEY,
                payload=json.loads(message.body),
                created_at=now,
                next_attempt_at=now,
                attempts=0,
            )
        )

    def claim_next(self, now: datetime) -> RecordedEventMessage | None:
        model = self._session.scalar(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.next_attempt_at <= now,
            )
            .order_by(
                OutboxEventModel.next_attempt_at,
                OutboxEventModel.created_at,
                OutboxEventModel.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if model is None:
            return None
        return RecordedEventMessage(
            message_id=model.id,
            event_id=model.event_id,
            shipment_id=model.shipment_id,
            body=json.dumps(model.payload, sort_keys=True, separators=(",", ":")),
        )

    def mark_published(self, message_id: UUID, now: datetime) -> None:
        model = self._get(message_id)
        model.attempts += 1
        model.published_at = now
        model.last_error = None

    def mark_failed(self, message_id: UUID, *, retry_at: datetime, error: str) -> None:
        model = self._get(message_id)
        model.attempts += 1
        model.next_attempt_at = retry_at
        model.last_error = error[:100]

    def _get(self, message_id: UUID) -> OutboxEventModel:
        model = self._session.get(OutboxEventModel, message_id)
        if model is None:
            raise LookupError("Claimed outbox message no longer exists")
        return model
