from contextlib import asynccontextmanager

from app.api.routes.events import router as events_router
from app.api.routes.shipments import router as shipments_router
from app.api.schemas.health import HealthResponse
from app.infra.observability.http import ObservabilityMiddleware
from app.infra.observability.logging import configure_logging
from app.infra.observability.metrics import Metrics
from fastapi import FastAPI
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import JSONResponse, Response


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging()
    yield


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
        lifespan=lifespan,
    )

    metrics = Metrics()
    application.state.metrics = metrics
    application.add_middleware(ObservabilityMiddleware, metrics=metrics)

    @application.exception_handler(Exception)
    async def server_error(request, error):
        return JSONResponse(
            {"detail": "Internal Server Error"},
            status_code=500,
            headers={"X-Correlation-ID": request.state.correlation_id},
        )

    @application.get("/metrics", include_in_schema=False)
    def metrics_endpoint():
        return Response(
            generate_latest(metrics.registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
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
