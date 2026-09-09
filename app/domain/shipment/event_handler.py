from app.domain.shipment.entities import Shipment
from app.domain.shipment.events import (
    LocationUpdatedPayload,
    ShipmentEvent,
    ShipmentEventProcessingStatus,
    ShipmentEventType,
)
from app.domain.shipment.exceptions import InvalidShipmentEvent


class ShipmentEventHandler:
    def handle(
        self,
        shipment: Shipment,
        event: ShipmentEvent,
    ) -> ShipmentEventProcessingStatus:
        if event.shipment_id != shipment.id:
            raise ValueError("Event shipment_id does not match the target shipment id.")

        if event.event_type == ShipmentEventType.SHIPMENT_CREATED:
            raise InvalidShipmentEvent(event.event_type.value)

        if event.event_type == ShipmentEventType.LOCATION_UPDATED:
            payload = event.payload

            if isinstance(payload, dict):
                try:
                    payload = LocationUpdatedPayload(**payload)
                except TypeError as error:
                    raise ValueError(
                        "LOCATION_UPDATED events require latitude and longitude."
                    ) from error

            if not isinstance(payload, LocationUpdatedPayload):
                raise ValueError(
                    "LOCATION_UPDATED events require a LocationUpdatedPayload."
                )

            if (
                shipment.last_location_at is not None
                and event.occurred_at < shipment.last_location_at
            ):
                return ShipmentEventProcessingStatus.STORED_OUT_OF_ORDER

            shipment.update_location(
                payload=payload,
                occurred_at=event.occurred_at,
            )
            return ShipmentEventProcessingStatus.APPLIED

        if (
            shipment.last_lifecycle_at is not None
            and event.occurred_at < shipment.last_lifecycle_at
        ):
            return ShipmentEventProcessingStatus.STORED_OUT_OF_ORDER

        shipment.change_status(
            event.event_type,
            event.occurred_at,
        )
        return ShipmentEventProcessingStatus.APPLIED
