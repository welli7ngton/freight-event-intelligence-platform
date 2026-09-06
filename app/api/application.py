from app.api.routes.events import router as events_router
from app.api.routes.shipments import router as shipments_router
from fastapi import FastAPI


def create_application() -> FastAPI:
    application = FastAPI(
        title="Freight Event Intelligence Platform",
        version="0.1.0",
    )

    application.include_router(shipments_router)
    application.include_router(events_router)

    @application.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_application()
