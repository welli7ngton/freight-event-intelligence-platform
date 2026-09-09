from app.domain.shipment.entities import Shipment
from app.domain.shipment.state_machine import ShipmentStatus
from app.infra.database.models.shipment import ShipmentModel


def to_domain(model: ShipmentModel) -> Shipment:
    return Shipment(
        id=model.id,
        reference_number=model.reference_number,
        origin=model.origin,
        destination=model.destination,
        carrier=model.carrier,
        status=ShipmentStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        current_latitude=model.current_latitude,
        current_longitude=model.current_longitude,
        last_location_at=model.last_location_at,
        last_lifecycle_at=model.last_lifecycle_at,
    )


def to_model(shipment: Shipment) -> ShipmentModel:
    return ShipmentModel(
        id=shipment.id,
        reference_number=shipment.reference_number,
        origin=shipment.origin,
        destination=shipment.destination,
        carrier=shipment.carrier,
        status=shipment.status.value,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        current_latitude=shipment.current_latitude,
        current_longitude=shipment.current_longitude,
        last_location_at=shipment.last_location_at,
        last_lifecycle_at=shipment.last_lifecycle_at,
    )
