import json
import socket
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from time import monotonic
from unittest.mock import Mock
from uuid import uuid4

import pika
import pytest
from app.application.messaging.recorded_event_message import (
    EVENT_RECORDED_ROUTING_KEY,
    RecordedEventMessage,
)
from app.application.messaging.shipment_event_message import ShipmentEventMessage
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.application.use_cases.publish_outbox_event import PublishOutboxEvent
from app.domain.shipment.events import ShipmentEventType
from app.infra.database.models.outbox_event import OutboxEventModel
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.infra.messaging.outbox import RabbitMQRecordedEventPublisher, _Publication
from app.infra.messaging.rabbitmq import RabbitMQShipmentEventConsumer
from app.workers import shipment_event_worker
from app.workers.outbox_worker import publish_one
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from tests.factories.shipment import make_event, make_shipment

pytestmark = pytest.mark.integration


@pytest.fixture
def outbound(rabbitmq_url):
    suffix = uuid4().hex
    exchange, queue = f"outbox-test-{suffix}", f"outbox-queue-{suffix}"
    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    publisher = RabbitMQRecordedEventPublisher(
        url=rabbitmq_url, exchange=exchange, queue=queue, timeout_seconds=3
    )
    try:
        yield publisher, channel, exchange, queue
    finally:
        channel.queue_delete(queue=queue)
        channel.exchange_delete(exchange=exchange)
        connection.close()


def seed(session):
    shipment = CreateShipment(
        SQLAlchemyShipmentRepository(session),
        SQLAlchemyShipmentEventRepository(session),
        SQLAlchemyOutboxRepository(session),
    ).execute(CreateShipmentInput("OUTBOX-BROKER", "Fortaleza", "Recife", "Carrier A"))
    session.commit()
    return shipment


def test_relay_confirms_real_delivery_and_marks_published(
    db_session, integration_engine, outbound
):
    publisher, channel, exchange, queue = outbound
    incoming_exchange = f"{exchange}-incoming"
    channel.exchange_declare(exchange=incoming_exchange, exchange_type="topic")
    incoming_queue = channel.queue_declare(queue="", exclusive=True).method.queue
    channel.queue_bind(
        exchange=incoming_exchange,
        queue=incoming_queue,
        routing_key="shipment.event.received.v1",
    )
    seed(db_session)
    factory = sessionmaker(integration_engine, expire_on_commit=False)
    assert publish_one(factory, publisher, retry_delay=timedelta(seconds=5))
    method, props, body = channel.basic_get(queue=queue, auto_ack=True)
    assert method is not None and props.delivery_mode == 2
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        assert json.loads(body) == row.payload
        assert props.message_id == str(row.id)
        assert row.published_at is not None and row.attempts == 1
    assert not publish_one(factory, publisher, retry_delay=timedelta(seconds=5))
    assert channel.basic_get(queue=incoming_queue, auto_ack=True)[0] is None
    channel.exchange_delete(exchange=incoming_exchange)


def test_unroutable_publication_stays_pending(
    db_session, integration_engine, outbound, monkeypatch
):
    publisher, channel, exchange, queue = outbound
    seed(db_session)
    original = _Publication.on_bound

    def remove_binding(attempt, frame):
        attempt.channel.queue_unbind(
            queue=queue,
            exchange=exchange,
            routing_key=EVENT_RECORDED_ROUTING_KEY,
            callback=lambda reply: original(attempt, reply),
        )

    monkeypatch.setattr(_Publication, "on_bound", remove_binding)
    assert publish_one(
        sessionmaker(integration_engine), publisher, retry_delay=timedelta(seconds=5)
    )
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        assert row.published_at is None and row.last_error == "UnroutableError"
    assert channel.basic_get(queue=queue, auto_ack=True)[0] is None


def test_confirmed_publish_then_commit_failure_republishes_identical_body(
    db_session, integration_engine, outbound
):
    publisher, channel, exchange, queue = outbound
    seed(db_session)

    class FailingCommit(Session):
        pass

    from sqlalchemy import event

    def fail_commit(session):
        raise RuntimeError("commit failed after publication")

    event.listen(FailingCommit, "before_commit", fail_commit)
    with pytest.raises(RuntimeError):
        publish_one(
            sessionmaker(integration_engine, class_=FailingCommit),
            publisher,
            retry_delay=timedelta(seconds=5),
        )
    assert publish_one(
        sessionmaker(integration_engine), publisher, retry_delay=timedelta(seconds=5)
    )
    first = channel.basic_get(queue=queue, auto_ack=True)
    second = channel.basic_get(queue=queue, auto_ack=True)
    assert first[0] is not None and second[0] is not None
    assert first[1].message_id == second[1].message_id
    assert first[2] == second[2]


def test_worker_commits_event_and_intent_before_ack_and_deduplicates(
    db_session, integration_engine, monkeypatch
):
    shipment = make_shipment(reference_number="WORKER-OUTBOX")
    SQLAlchemyShipmentRepository(db_session).save(shipment)
    db_session.commit()
    factory = sessionmaker(integration_engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(shipment_event_worker, "SessionLocal", factory)
    event = make_event(shipment=shipment)
    message = ShipmentEventMessage.from_event(message_id=uuid4(), event=event)
    channel = Mock()

    def observe_commit(**kwargs):
        with Session(integration_engine) as observer:
            rows = observer.scalars(select(OutboxEventModel)).all()
            assert len(rows) == 1
            assert rows[0].event_id == event.event_id

    channel.basic_ack.side_effect = observe_commit
    consumer = RabbitMQShipmentEventConsumer(
        url="amqp://guest:guest@localhost/%2F", exchange="unused", queue="unused"
    )
    for _ in range(2):
        consumer.process_delivery(
            channel=channel,
            delivery_tag=1,
            body=message.to_json().encode(),
            handle_event=shipment_event_worker.handle_event,
        )
    assert channel.basic_ack.call_count == 2
    channel.basic_publish.assert_not_called()

    late_event = make_event(
        shipment=shipment,
        event_type=ShipmentEventType.PICKUP_COMPLETED,
        occurred_at=event.occurred_at - timedelta(minutes=1),
    )
    channel.basic_ack.side_effect = None
    consumer.process_delivery(
        channel=channel,
        delivery_tag=2,
        body=ShipmentEventMessage.from_event(message_id=uuid4(), event=late_event)
        .to_json()
        .encode(),
        handle_event=shipment_event_worker.handle_event,
    )
    with Session(integration_engine) as observer:
        rows = observer.scalars(select(OutboxEventModel)).all()
        assert len(rows) == 2
        late_row = next(row for row in rows if row.event_id == late_event.event_id)
        assert late_row.payload["processing_status"] == "STORED_OUT_OF_ORDER"


def test_silent_tcp_peer_hits_deadline_without_leaking_thread():
    # A peer accepting TCP but never completing AMQP must not hold a DB row forever.
    stop = Event()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(2)
        port = listener.getsockname()[1]

        def silent_peer():
            with listener.accept()[0]:
                stop.wait(3)

        thread = Thread(target=silent_peer)
        thread.start()
        publisher = RabbitMQRecordedEventPublisher(
            url=f"amqp://guest:guest@127.0.0.1:{port}/%2F",
            exchange="unused",
            queue="unused",
            timeout_seconds=0.2,
        )
        start = monotonic()
        try:
            with pytest.raises(TimeoutError):
                publisher.publish(
                    RecordedEventMessage.from_event(
                        make_event(shipment=make_shipment())
                    )
                )
        finally:
            stop.set()
            thread.join(timeout=3)
        assert monotonic() - start < 2
        assert not thread.is_alive()


def test_confirmation_deadline_aborts_open_connection(outbound, monkeypatch):
    publisher, channel, exchange, queue = outbound
    # Broker/transport are alive; suppress the confirm handler to reproduce a
    # publisher waiting indefinitely for completion despite heartbeats.
    monkeypatch.setattr(_Publication, "on_confirmation", lambda *_: None)
    publisher._timeout = 0.3
    with pytest.raises(TimeoutError):
        publisher.publish(
            RecordedEventMessage.from_event(make_event(shipment=make_shipment()))
        )


def test_real_broker_connection_failure_recovers_on_later_attempt(
    db_session, integration_engine, outbound
):
    publisher, channel, exchange, queue = outbound
    seed(db_session)
    offline = RabbitMQRecordedEventPublisher(
        url="amqp://guest:guest@127.0.0.1:1/%2F",
        exchange=exchange,
        queue=queue,
        timeout_seconds=0.3,
    )
    now = datetime.now(UTC)
    with Session(integration_engine) as session, session.begin():
        assert PublishOutboxEvent(
            SQLAlchemyOutboxRepository(session),
            offline,
            retry_delay=timedelta(seconds=5),
            clock=lambda: now,
        ).execute()
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        assert row.published_at is None and row.attempts == 1
    now += timedelta(seconds=5)
    with Session(integration_engine) as session, session.begin():
        assert PublishOutboxEvent(
            SQLAlchemyOutboxRepository(session),
            publisher,
            retry_delay=timedelta(seconds=5),
            clock=lambda: now,
        ).execute()
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        assert row.published_at is not None and row.attempts == 2
    assert channel.basic_get(queue=queue, auto_ack=True)[0] is not None
