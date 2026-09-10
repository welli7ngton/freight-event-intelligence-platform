from typing import Protocol

from app.application.messaging.recorded_event_message import RecordedEventMessage


class RecordedEventPublisher(Protocol):
    def publish(self, message: RecordedEventMessage) -> None:
        """Return only after routed publication is confirmed; otherwise raise."""
        ...
