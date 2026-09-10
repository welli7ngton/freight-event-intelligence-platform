import logging
import signal
from datetime import timedelta
from threading import Event

from app.application.use_cases.publish_outbox_event import PublishOutboxEvent
from app.infra.config import get_database_url, get_outbox_settings, get_rabbitmq_url
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.session import SessionLocal
from app.infra.messaging.outbox import RabbitMQRecordedEventPublisher
from app.infra.observability.backlog import OutboxBacklogCollector
from app.infra.observability.context import observation_context
from app.infra.observability.logging import configure_logging, observe
from app.infra.observability.metrics import metrics_server, worker_metrics
from app.infra.observability.publication import ObservedPublisher, message_context
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


def publish_one(session_factory, publisher, *, retry_delay: timedelta) -> bool:
    observed = ObservedPublisher(publisher, worker_metrics)
    try:
        with session_factory() as session, session.begin():
            result = PublishOutboxEvent(
                SQLAlchemyOutboxRepository(session), observed, retry_delay=retry_delay
            ).execute()
    except Exception as error:
        worker_metrics.outbox.labels("transaction_failed").inc()
        fields = (
            message_context(observed.message)
            if observed.message
            else {"component": "outbox"}
        )
        with observation_context(**fields):
            observe(
                logger,
                "outbox_transaction",
                outcome="rolled_back",
                error_type=type(error).__name__,
            )
        raise
    if result is None:
        return False
    outcome = "published_committed" if result.confirmed else "retry_committed"
    worker_metrics.outbox.labels(outcome).inc()
    with observation_context(**message_context(result.message)):
        observe(
            logger, "outbox_transaction", outcome=outcome, error_type=result.error_type
        )
    return True


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
            observe(
                logger,
                "outbox_reconnect",
                component="outbox",
                outcome="waiting",
                error_type=type(error).__name__,
            )
            stop.wait(settings.retry_seconds)
        else:
            if not worked:
                stop.wait(settings.poll_seconds)


def main() -> None:
    configure_logging("outbox")
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
    # Separate small pool: a scrape must not wait on the relay's broker transaction.
    engine = create_engine(
        get_database_url(),
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
        connect_args={"connect_timeout": 2},
    )
    collector = OutboxBacklogCollector(sessionmaker(engine))
    worker_metrics.registry.register(collector)
    try:
        with metrics_server(worker_metrics, "OUTBOX_METRICS_PORT", 9102):
            run(SessionLocal, publisher, settings=settings, stop=stop)
    finally:
        worker_metrics.registry.unregister(collector)
        engine.dispose()


if __name__ == "__main__":
    main()
