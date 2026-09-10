import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pika
import pytest
from app.application.messaging.recorded_event_message import RecordedEventMessage
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.application.use_cases.publish_outbox_event import PublishOutboxEvent
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import ShipmentEventType
from app.domain.shipment.exceptions import InvalidStateTransition
from tests.factories.repositories import (
    InMemoryOutboxRepository,
    InMemoryShipmentEventRepository,
    InMemoryShipmentRepository,
)
from tests.factories.shipment import make_event, make_shipment


def test_creation_and_ingestion_record_notifications_and_skip_duplicates():
    shipments = InMemoryShipmentRepository()
    events = InMemoryShipmentEventRepository()
    outbox = InMemoryOutboxRepository()
    shipment = CreateShipment(shipments, events, outbox).execute(
        CreateShipmentInput("OUTBOX-001", "Fortaleza", "Recife", "Carrier A")
    )
    receive = ReceiveShipmentEvent(shipments, events, ShipmentEventHandler(), outbox)
    now = datetime.now(UTC)
    event = make_event(shipment=shipment, occurred_at=now)
    receive.execute(event)
    receive.execute(event)
    receive.execute(
        make_event(
            shipment=shipment,
            event_type=ShipmentEventType.PICKUP_COMPLETED,
            occurred_at=now - timedelta(minutes=1),
        )
    )

    envelopes = [json.loads(message.body) for message in outbox.items.values()]
    assert len(events.items) == len(envelopes) == 3
    assert [body["event_type"] for body in envelopes] == [
        "SHIPMENT_CREATED",
        "PICKUP_SCHEDULED",
        "PICKUP_COMPLETED",
    ]
    assert [body["processing_status"] for body in envelopes] == [
        "APPLIED",
        "APPLIED",
        "STORED_OUT_OF_ORDER",
    ]
    assert all(
        body["message_type"] == "shipment.event.recorded.v1" for body in envelopes
    )


def test_rejected_event_does_not_enqueue():
    shipment = make_shipment()
    shipments = InMemoryShipmentRepository()
    shipments.save(shipment)
    outbox = InMemoryOutboxRepository()
    receive = ReceiveShipmentEvent(
        shipments, InMemoryShipmentEventRepository(), ShipmentEventHandler(), outbox
    )
    with pytest.raises(InvalidStateTransition):
        receive.execute(
            make_event(shipment=shipment, event_type=ShipmentEventType.DELIVERED)
        )
    assert not outbox.items


def test_message_is_an_immutable_serialized_snapshot():
    payload = {"location": {"name": "original"}}
    event = make_event(shipment=make_shipment(), payload=payload)
    message = RecordedEventMessage.from_event(event)
    payload["location"]["name"] = "changed"
    assert json.loads(message.body)["payload"]["location"]["name"] == "original"
    assert json.loads(message.body)["message_id"] == str(message.message_id)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("secret-url"),
        pika.exceptions.NackError([]),
        pika.exceptions.UnroutableError([]),
    ],
)
def test_failed_publication_is_delayed_and_reuses_same_identity(error):
    outbox = InMemoryOutboxRepository()
    message = RecordedEventMessage.from_event(make_event(shipment=make_shipment()))
    outbox.add(message)
    publisher = Mock()
    publisher.publish.side_effect = error
    now = datetime.now(UTC)
    relay = PublishOutboxEvent(
        outbox, publisher, retry_delay=timedelta(seconds=5), clock=lambda: now
    )
    assert relay.execute()
    assert not outbox.published
    assert outbox.failures[message.message_id] == (
        now + timedelta(seconds=5),
        type(error).__name__,
    )
    assert not relay.execute()
    now += timedelta(seconds=5)
    publisher.publish.side_effect = None
    assert relay.execute()
    assert publisher.publish.call_args_list[0] == publisher.publish.call_args_list[1]
    assert outbox.published[message.message_id] == now
    assert not relay.execute()


def test_interruption_does_not_mark_success_or_swallow_shutdown():
    outbox = InMemoryOutboxRepository()
    outbox.add(RecordedEventMessage.from_event(make_event(shipment=make_shipment())))
    publisher = Mock()
    publisher.publish.side_effect = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        PublishOutboxEvent(
            outbox, publisher, retry_delay=timedelta(seconds=5)
        ).execute()
    assert not outbox.published and not outbox.failures
