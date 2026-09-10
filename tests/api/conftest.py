import pytest
from app.api.application import app
from app.api.dependencies import (
    get_create_shipment_use_case,
    get_db,
    get_get_shipment_events_use_case,
    get_get_shipment_use_case,
    get_receive_shipment_event_use_case,
)
from app.application.use_cases.create_shipment import CreateShipment
from app.application.use_cases.get_shipment import GetShipment
from app.application.use_cases.get_shipment_events import GetShipmentEvents
from app.application.use_cases.receive_shipment_events import ReceiveShipmentEvent
from app.domain.shipment.event_handler import ShipmentEventHandler
from fastapi.testclient import TestClient
from tests.factories.repositories import InMemoryOutboxRepository


class InMemoryTransaction:
    def flush(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture
def repositories(in_memory_repositories):
    shipment_repository, event_repository = in_memory_repositories

    app.dependency_overrides[get_create_shipment_use_case] = lambda: CreateShipment(
        shipment_repository,
        event_repository,
        InMemoryOutboxRepository(),
    )
    app.dependency_overrides[get_get_shipment_use_case] = lambda: GetShipment(
        shipment_repository,
    )
    app.dependency_overrides[get_get_shipment_events_use_case] = (
        lambda: GetShipmentEvents(event_repository)
    )
    app.dependency_overrides[get_receive_shipment_event_use_case] = (
        lambda: ReceiveShipmentEvent(
            shipment_repository=shipment_repository,
            shipment_event_repository=event_repository,
            outbox_repository=InMemoryOutboxRepository(),
            event_handler=ShipmentEventHandler(),
        )
    )
    app.dependency_overrides[get_db] = lambda: InMemoryTransaction()

    try:
        yield shipment_repository, event_repository
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client(repositories):
    return TestClient(app)
