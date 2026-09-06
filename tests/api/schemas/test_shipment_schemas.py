import pytest
from app.api.schemas.shipment import CreateShipmentRequest
from pydantic import ValidationError


def test_create_shipment_request_accepts_valid_data():
    request = CreateShipmentRequest(
        reference_number="SHIP-001",
        origin="Fortaleza",
        destination="São Paulo",
        carrier="Carrier A",
    )

    assert request.reference_number == "SHIP-001"
    assert request.origin == "Fortaleza"
    assert request.destination == "São Paulo"
    assert request.carrier == "Carrier A"


def test_create_shipment_request_rejects_empty_reference():
    with pytest.raises(ValidationError):
        CreateShipmentRequest(
            reference_number="",
            origin="Fortaleza",
            destination="São Paulo",
            carrier="Carrier A",
        )


def test_create_shipment_request_rejects_empty_origin():
    with pytest.raises(ValidationError):
        CreateShipmentRequest(
            reference_number="SHIP-001",
            origin="",
            destination="São Paulo",
            carrier="Carrier A",
        )
