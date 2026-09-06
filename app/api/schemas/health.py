from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness status returned by the API health endpoint."""

    status: str = Field(
        description="Current liveness status of the API process.",
        examples=["ok"],
    )
