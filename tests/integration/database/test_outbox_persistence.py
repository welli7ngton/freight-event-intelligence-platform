from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from app.application.messaging.recorded_event_message import RecordedEventMessage
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.application.use_cases.publish_outbox_event import PublishOutboxEvent
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.infra.database.models.outbox_event import OutboxEventModel
from app.infra.database.models.shipment import ShipmentModel
from app.infra.database.models.shipment_event import ShipmentEventModel
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.workers.outbox_worker import publish_one
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from tests.factories.shipment import make_event

pytestmark = pytest.mark.integration


def create(session, outbox=None):
    return CreateShipment(
        SQLAlchemyShipmentRepository(session),
        SQLAlchemyShipmentEventRepository(session),
        outbox if outbox is not None else SQLAlchemyOutboxRepository(session),
    ).execute(CreateShipmentInput("OUTBOX-DB", "Fortaleza", "Recife", "Carrier A"))


def test_creation_commits_all_three_records(db_session, integration_engine):
    shipment = create(db_session)
    db_session.commit()
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        event = observer.get(ShipmentEventModel, row.event_id)
        assert observer.get(ShipmentModel, shipment.id) is not None
        assert row.payload["event_id"] == str(event.event_id)
        assert row.payload["event_type"] == "SHIPMENT_CREATED"
        assert row.payload["processing_status"] == "APPLIED"
        assert row.payload["message_id"] == str(row.id)
        assert row.published_at is None and row.attempts == 0


class FailAfterFlush(SQLAlchemyOutboxRepository):
    def add(self, message):
        super().add(message)
        self._session.flush()
        raise RuntimeError("failure after writes reached PostgreSQL")


def test_creation_rollback_removes_flushed_state_history_and_intent(
    db_session, integration_engine
):
    with pytest.raises(RuntimeError):
        create(db_session, FailAfterFlush(db_session))
    db_session.rollback()
    with Session(integration_engine) as observer:
        for model in (ShipmentModel, ShipmentEventModel, OutboxEventModel):
            assert observer.scalar(select(func.count()).select_from(model)) == 0


def test_event_rollback_preserves_previous_projection(db_session, integration_engine):
    shipment = create(db_session)
    db_session.commit()
    receive = ReceiveShipmentEvent(
        SQLAlchemyShipmentRepository(db_session),
        SQLAlchemyShipmentEventRepository(db_session),
        ShipmentEventHandler(),
        FailAfterFlush(db_session),
    )
    with pytest.raises(RuntimeError):
        receive.execute(make_event(shipment=shipment))
    db_session.rollback()
    with Session(integration_engine) as observer:
        assert observer.get(ShipmentModel, shipment.id).status == "CREATED"
        assert (
            observer.scalar(select(func.count()).select_from(ShipmentEventModel)) == 1
        )
        assert observer.scalar(select(func.count()).select_from(OutboxEventModel)) == 1


def test_locked_row_is_skipped_and_released_after_rollback(
    db_session, integration_engine
):
    shipment = create(db_session)
    event = make_event(shipment=shipment)
    SQLAlchemyShipmentEventRepository(db_session).save(event)
    SQLAlchemyOutboxRepository(db_session).add(RecordedEventMessage.from_event(event))
    db_session.commit()
    now = datetime.now(UTC)
    with Session(integration_engine) as first, Session(integration_engine) as second:
        one = SQLAlchemyOutboxRepository(first).claim_next(now)
        two = SQLAlchemyOutboxRepository(second).claim_next(now)
        assert one.message_id != two.message_id
        with Session(integration_engine) as third:
            assert SQLAlchemyOutboxRepository(third).claim_next(now) is None
        first.rollback()
        with Session(integration_engine) as third:
            assert SQLAlchemyOutboxRepository(third).claim_next(now) == one


def test_broker_failure_keeps_intent_and_persists_retry_metadata(
    db_session, integration_engine
):
    create(db_session)
    db_session.commit()
    publisher = Mock()
    publisher.publish.side_effect = TimeoutError("amqp://secret@broker")
    now = datetime.now(UTC)
    with Session(integration_engine) as session, session.begin():
        assert PublishOutboxEvent(
            SQLAlchemyOutboxRepository(session),
            publisher,
            retry_delay=timedelta(seconds=5),
            clock=lambda: now,
        ).execute()
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        assert row.attempts == 1 and row.published_at is None
        assert row.last_error == "TimeoutError"
        assert row.next_attempt_at == now + timedelta(seconds=5)
        assert SQLAlchemyOutboxRepository(observer).claim_next(now) is None


def test_failure_after_publication_replays_same_envelope(
    db_session, integration_engine
):
    create(db_session)
    db_session.commit()
    publisher = Mock()
    with Session(integration_engine) as session:
        assert PublishOutboxEvent(
            SQLAlchemyOutboxRepository(session),
            publisher,
            retry_delay=timedelta(seconds=5),
        ).execute()
        session.flush()
        session.rollback()  # Simulate failure between broker confirm and DB commit.
    factory = sessionmaker(integration_engine, expire_on_commit=False)
    assert publish_one(factory, publisher, retry_delay=timedelta(seconds=5))
    assert publisher.publish.call_args_list[0] == publisher.publish.call_args_list[1]
    assert not publish_one(factory, publisher, retry_delay=timedelta(seconds=5))
    with Session(integration_engine) as observer:
        row = observer.scalar(select(OutboxEventModel))
        assert row.attempts == 1 and row.published_at is not None
