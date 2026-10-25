"""Request bodies and response/error models (these feed the OpenAPI spec)."""
from pydantic import BaseModel, ConfigDict, Field


class StrictBody(BaseModel):
    """Base for request bodies: unknown fields are rejected with a 422 instead of silently ignored."""
    model_config = ConfigDict(extra="forbid")


# ---------- request bodies ----------

class AvailabilityUpdate(StrictBody):
    available: bool
    portions_left: int | None = Field(default=None, ge=0, le=500)


class HoldCreate(StrictBody):
    item_id: int = Field(gt=0, description="ID of the menu item to hold")
    pickup_in_minutes: int = Field(default=180, ge=15, le=480,
                                   description="Planned pickup time, 15-480 minutes from now")


class FaultConfig(StrictBody):
    """Fault injection knobs used by Experiment E1. All zero means no fault."""
    menu_delay_ms: int = Field(default=0, ge=0, le=5000)
    menu_delay_every_nth: int = Field(default=1, ge=1, le=1000)
    hold_fail_every_nth: int = Field(default=0, ge=0, le=1000)


# ---------- error envelope (one shape for every error) ----------

class ErrorDetail(BaseModel):
    code: str = Field(examples=["ITEM_SOLD_OUT"])
    message: str = Field(examples=["item is sold out"])
    request_id: str | None = None
    details: list[dict] | None = Field(default=None, description="Field-level errors for 422 responses")


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------- responses (used as response_model so the spec matches reality) ----------

class HoldOut(BaseModel):
    id: int
    item_id: int
    eatery: str
    pickup_code: str
    status: str
    planned_pickup_minutes: int


class ItemOut(BaseModel):
    id: int
    name: str
    eatery: str
    portions_left: int
    available: bool