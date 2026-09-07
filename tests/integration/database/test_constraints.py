import pytest
from app.infra.database.repositories.event import SQLAlchemyShipmentEventRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository
from sqlalchemy.exc import IntegrityError
from tests.factories.shipment import make_event, make_shipment

pytestmark = pytest.mark.integration


def test_database_rejects_duplicate_shipment_reference(db_session) -> None:
    repository = SQLAlchemyShipmentRepository(db_session)
    repository.save(make_shipment(reference_number="DUPLICATE-REFERENCE"))
    db_session.commit()

    repository.save(make_shipment(reference_number="DUPLICATE-REFERENCE"))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_duplicate_event_id(db_session) -> None:
    shipment = make_shipment(reference_number="EVENT-ID-CONSTRAINT")
    shipment_repository = SQLAlchemyShipmentRepository(db_session)
    event_repository = SQLAlchemyShipmentEventRepository(db_session)
    event = make_event(shipment=shipment)

    shipment_repository.save(shipment)
    event_repository.save(event)
    db_session.commit()

    event_repository.save(event)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_event_for_unknown_shipment(db_session) -> None:
    event_repository = SQLAlchemyShipmentEventRepository(db_session)
    event = make_event(shipment=make_shipment())

    event_repository.save(event)

    with pytest.raises(IntegrityError):
        db_session.commit()
