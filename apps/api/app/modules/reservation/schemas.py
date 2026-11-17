from datetime import datetime

from pydantic import BaseModel


class ReservationCreate(BaseModel):
    planned_return_at: datetime
    reason: str = ""


class ReservationPatch(BaseModel):
    expected_version: int
    planned_return_at: datetime | None = None
    reason: str | None = None


class VersionedAction(BaseModel):
    expected_version: int
