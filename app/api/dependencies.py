from collections.abc import Generator

from app.application.use_cases.create_shipment import CreateShipment
from app.application.use_cases.get_shipment import GetShipment
from app.application.use_cases.get_shipment_events import GetShipmentEvents
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from app.infra.database.session import SessionLocal
from fastapi import Depends
from sqlalchemy.orm import Session


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_shipment_repository(
    db: Session = Depends(get_db),
):
    return SQLAlchemyShipmentRepository(db)


def get_event_repository(
    db: Session = Depends(get_db),
):
    return SQLAlchemyShipmentEventRepository(db)


def get_create_shipment_use_case(
    db: Session = Depends(get_db),
) -> CreateShipment:
    repository = SQLAlchemyShipmentRepository(db)

    return CreateShipment(repository)


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
) -> ReceiveShipmentEvent:
    shipment_repository = SQLAlchemyShipmentRepository(db)
    event_repository = SQLAlchemyShipmentEventRepository(db)

    return ReceiveShipmentEvent(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        event_handler=ShipmentEventHandler(),
    )
