from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.application.ports.outbox_repository import OutboxRepository
from app.application.ports.recorded_event_publisher import RecordedEventPublisher


def utc_now() -> datetime:
    return datetime.now(UTC)


class PublishOutboxEvent:
    def __init__(
        self,
        repository: OutboxRepository,
        publisher: RecordedEventPublisher,
        *,
        retry_delay: timedelta,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._publisher = publisher
        self._retry_delay = retry_delay
        self._clock = clock

    def execute(self) -> bool:
        message = self._repository.claim_next(self._clock())
        if message is None:
            return False
        try:
            self._publisher.publish(message)
        except Exception as error:
            # Exception strings can contain broker URLs, credentials or payloads.
            self._repository.mark_failed(
                message.message_id,
                retry_at=self._clock() + self._retry_delay,
                error=type(error).__name__[:100],
            )
        else:
            self._repository.mark_published(message.message_id, self._clock())
        return True
