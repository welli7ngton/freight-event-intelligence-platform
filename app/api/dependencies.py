import logging
from collections.abc import Generator
from time import monotonic

from app.application.use_cases.create_shipment import CreateShipment
from app.application.use_cases.get_shipment import GetShipment
from app.application.use_cases.get_shipment_events import GetShipmentEvents
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.infra.database.session import SessionLocal
from app.infra.observability.context import current_context
from app.infra.observability.logging import observe
from fastapi import Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    started = monotonic()

    try:
        yield db
        db.commit()
        observe(
            logger,
            "database_transaction",
            component="api",
            outcome="committed",
            duration_seconds=monotonic() - started,
        )
    except Exception as error:
        db.rollback()
        observe(
            logger,
            "database_transaction",
            component="api",
            outcome="rolled_back",
            error_type=type(error).__name__,
            duration_seconds=monotonic() - started,
        )
        raise
    finally:
        db.close()


def get_shipment_repository(db: Session = Depends(get_db)):
    return SQLAlchemyShipmentRepository(db)


def get_event_repository(db: Session = Depends(get_db)):
    return SQLAlchemyShipmentEventRepository(db)


def get_event_handler() -> ShipmentEventHandler:
    return ShipmentEventHandler()


def get_create_shipment_use_case(
    db: Session = Depends(get_db),
) -> CreateShipment:
    shipment_repository = SQLAlchemyShipmentRepository(db)
    shipment_event_repository = SQLAlchemyShipmentEventRepository(db)

    return CreateShipment(
        shipment_repository=shipment_repository,
        shipment_event_repository=shipment_event_repository,
        outbox_repository=SQLAlchemyOutboxRepository(db),
        correlation_id=current_context().get("correlation_id"),
    )


def get_get_shipment_use_case(
    db: Session = Depends(get_db),
) -> GetShipment:
    repository = SQLAlchemyShipmentRepository(db)

    return GetShipment(repository)


def get_get_shipment_events_use_case(
    db: Session = Depends(get_db),
) -> GetShipmentEvents:
    repository = SQLAlchemyShipmentEventRepository(db)

    return GetShipmentEvents(repository)


def get_receive_shipment_event_use_case(
    db: Session = Depends(get_db),
    event_handler: ShipmentEventHandler = Depends(get_event_handler),
) -> ReceiveShipmentEvent:
    shipment_repository = SQLAlchemyShipmentRepository(db)
    event_repository = SQLAlchemyShipmentEventRepository(db)

    return ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        event_handler=event_handler,
        outbox_repository=SQLAlchemyOutboxRepository(db),
        correlation_id=current_context().get("correlation_id"),
    )
