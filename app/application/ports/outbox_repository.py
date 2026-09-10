from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.messaging.recorded_event_message import RecordedEventMessage


class OutboxRepository(Protocol):
    def add(self, message: RecordedEventMessage) -> None: ...

    def claim_next(self, now: datetime) -> RecordedEventMessage | None:
        """Return one due message, exclusively owned until transaction end."""
        ...

    def mark_published(self, message_id: UUID, now: datetime) -> None: ...

    def mark_failed(
        self, message_id: UUID, *, retry_at: datetime, error: str
    ) -> None: ...
