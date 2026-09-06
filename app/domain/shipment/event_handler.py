from app.domain.shipment.entities import Shipment
from app.domain.shipment.events import (
    LocationUpdatedPayload,
    ShipmentEvent,
    ShipmentEventType,
)


class ShipmentEventHandler:
    def handle(
        self,
        shipment: Shipment,
        event: ShipmentEvent,
    ) -> None:
        if event.shipment_id != shipment.id:
            raise ValueError("Event shipment_id does not match the target shipment id.")

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

            shipment.update_location(
                payload=payload,
                occurred_at=event.occurred_at,
            )
            return

        shipment.change_status(
            event.event_type,
            event.occurred_at,
        )
