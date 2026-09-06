from app.api.routes.events import router as events_router
from app.api.routes.shipments import router as shipments_router
from app.api.schemas.health import HealthResponse
from fastapi import FastAPI

OPENAPI_TAGS = [
    {
        "name": "shipments",
        "description": "Create and query shipments and their event history.",
    },
    {
        "name": "events",
        "description": "Receive carrier and operational events for shipments.",
    },
    {
        "name": "health",
        "description": "Operational endpoints used to check service availability.",
    },
]


API_DESCRIPTION = """
## Freight Event Intelligence Platform

Event-driven API for tracking freight shipments, processing carrier events,
maintaining shipment state transitions, and recording the latest known location.

### Useful links

- [Project repo](https://github.com/welli7ngton/freight-event-intelligence-platform)
- Interactive documentation: `/docs`
- Alternative documentation: `/redoc`

For support, contact me at
[welli7ngton.dev@gmail.com](mailto:welli7ngton.dev@gmail.com).
"""


def create_application() -> FastAPI:
    application = FastAPI(
        title="Freight Event Intelligence Platform",
        description=API_DESCRIPTION,
        version="0.1.0",
        contact={
            "name": "Wellington Almeida",
            "email": "welli7ngton.dev@gmail.com",
            "url": "https://github.com/welli7ngton/freight-event-intelligence-platform/issues",
        },
        openapi_tags=OPENAPI_TAGS,
    )

    application.include_router(shipments_router)
    application.include_router(events_router)

    @application.get(
        "/health",
        tags=["health"],
        summary="Check API health",
        description="Returns a lightweight liveness response for the API process.",
        response_model=HealthResponse,
        response_description="The API process is healthy and accepting requests.",
    )
    def health_check() -> HealthResponse:
        return {"status": "ok"}

    return application


app = create_application()
