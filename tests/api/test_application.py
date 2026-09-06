from app.api.application import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_shipment_rejects_invalid_payload():
    response = client.post(
        "/shipments",
        json={
            "reference_number": "",
            "origin": "Fortaleza",
            "destination": "São Paulo",
            "carrier": "Carrier A",
        },
    )

    assert response.status_code == 422
