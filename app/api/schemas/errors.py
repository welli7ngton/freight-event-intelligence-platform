from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error envelope returned by an unsuccessful API request."""

    detail: str = Field(
        description="Human-readable explanation of why the request failed.",
        examples=["Shipment not found"],
    )
