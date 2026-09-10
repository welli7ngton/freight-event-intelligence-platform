import logging
import signal
from datetime import timedelta
from threading import Event

from app.application.use_cases.publish_outbox_event import PublishOutboxEvent
from app.infra.config import get_outbox_settings, get_rabbitmq_url
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.session import SessionLocal
from app.infra.messaging.outbox import RabbitMQRecordedEventPublisher
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def publish_one(session_factory, publisher, *, retry_delay: timedelta) -> bool:
    with session_factory() as session, session.begin():
        return PublishOutboxEvent(
            SQLAlchemyOutboxRepository(session), publisher, retry_delay=retry_delay
        ).execute()


def run(session_factory, publisher, *, settings, stop: Event) -> None:
    while not stop.is_set():
        try:
            worked = publish_one(
                session_factory,
                publisher,
                retry_delay=timedelta(seconds=settings.retry_seconds),
            )
        except SQLAlchemyError as error:
            # Do not log connection URLs or SQL parameters from exception strings.
            logger.warning("Outbox database attempt failed: %s", type(error).__name__)
            stop.wait(settings.retry_seconds)
        else:
            if not worked:
                stop.wait(settings.poll_seconds)


def main() -> None:
    settings = get_outbox_settings()
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    publisher = RabbitMQRecordedEventPublisher(
        url=get_rabbitmq_url(),
        exchange=settings.exchange,
        queue=settings.queue,
        timeout_seconds=settings.publish_timeout_seconds,
    )
    run(SessionLocal, publisher, settings=settings, stop=stop)


if __name__ == "__main__":
    main()
