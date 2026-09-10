import pytest
from app.application.use_cases.create_shipment import (
    CreateShipment,
    CreateShipmentInput,
)
from app.infra.database.models.shipment import ShipmentModel
from app.infra.database.repositories.outbox import SQLAlchemyOutboxRepository
from app.infra.database.repositories.shipment import SQLAlchemyShipmentRepository

pytestmark = pytest.mark.integration


class FailingShipmentEventRepository:
    def exists(self, event_id):
        return False

    def save(self, event):
        raise RuntimeError("event persistence failed")

    def list_by_shipment(self, shipment_id):
        return []


def test_create_shipment_rolls_back_when_event_persistence_fails(db_session):
    shipment_repository = SQLAlchemyShipmentRepository(db_session)
    event_repository = FailingShipmentEventRepository()

    use_case = CreateShipment(
        shipment_repository=shipment_repository,
        shipment_event_repository=event_repository,
        outbox_repository=SQLAlchemyOutboxRepository(db_session),
    )

    with pytest.raises(RuntimeError):
        use_case.execute(
            CreateShipmentInput(
                reference_number="REF-ROLLBACK",
                origin="Fortaleza",
                destination="Recife",
                carrier="Carrier A",
            )
        )

    db_session.rollback()

    assert (
        db_session.query(ShipmentModel)
        .filter_by(reference_number="REF-ROLLBACK")
        .first()
        is None
    )
