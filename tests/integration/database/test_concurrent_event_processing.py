from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.domain.shipment.events import ShipmentEvent
from app.domain.shipment.state_machine import ShipmentStatus
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from tests.factories.shipment import make_event, make_shipment

pytestmark = pytest.mark.integration


class BarrierShipmentEventHandler:
    def __init__(self, barrier: Barrier) -> None:
        self._barrier = barrier
        self._delegate = ShipmentEventHandler()

    def handle(self, shipment, event: ShipmentEvent):
        self._barrier.wait(timeout=5)
        return self._delegate.handle(shipment, event)


def test_same_event_processed_concurrently_hits_unique_constraint(
    db_session: Session,
    integration_engine,
) -> None:
    shipment = make_shipment(reference_number="CONCURRENT-EVENT-001")
    SQLAlchemyShipmentRepository(db_session).save(shipment)
    db_session.commit()

    event = make_event(
        shipment=shipment,
        occurred_at=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )
    barrier = Barrier(2)
    session_factory = sessionmaker(bind=integration_engine, expire_on_commit=False)

    def process(event_to_process: ShipmentEvent) -> str:
        with session_factory() as session:
            use_case = ReceiveShipmentEvent(
                shipment_repository=SQLAlchemyShipmentRepository(session),
                shipment_event_repository=SQLAlchemyShipmentEventRepository(session),
                event_handler=BarrierShipmentEventHandler(barrier),
            )
            try:
                use_case.execute(event_to_process)
                session.commit()
                return "processed"
            except IntegrityError:
                session.rollback()
                return "duplicate_conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(process, [event, event]))

    db_session.expire_all()
    restored_shipment = SQLAlchemyShipmentRepository(db_session).get(shipment.id)
    persisted_events = SQLAlchemyShipmentEventRepository(db_session).list_by_shipment(
        shipment.id
    )

    assert sorted(results) == ["duplicate_conflict", "processed"]
    assert restored_shipment is not None
    assert restored_shipment.status is ShipmentStatus.SCHEDULED
    assert [persisted_event.event_id for persisted_event in persisted_events] == [
        event.event_id
    ]
