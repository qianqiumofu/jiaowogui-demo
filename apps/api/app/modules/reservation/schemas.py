from datetime import datetime

from pydantic import BaseModel, AwareDatetime


class ReservationCreate(BaseModel):
    planned_return_at: AwareDatetime
    reason: str = ""


class ReservationPatch(BaseModel):
    expected_version: int
    planned_return_at: AwareDatetime | None = None
    reason: str | None = None


class VersionedAction(BaseModel):
    expected_version: int
