"""Request bodies."""
from pydantic import BaseModel, Field


class AvailabilityUpdate(BaseModel):
    available: bool
    portions_left: int | None = Field(default=None, ge=0, le=500)


class HoldCreate(BaseModel):
    item_id: int
    pickup_in_minutes: int = Field(default=180, ge=15, le=480)


class FaultConfig(BaseModel):
    """Fault injection knobs used by Experiment E1. All zero means no fault."""
    menu_delay_ms: int = Field(default=0, ge=0, le=5000)
    menu_delay_every_nth: int = Field(default=1, ge=1, le=1000)
    hold_fail_every_nth: int = Field(default=0, ge=0, le=1000)
