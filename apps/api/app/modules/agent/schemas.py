from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ReportRequest(StrictModel):
    message: str = Field(min_length=1, max_length=1000)
    previous_messages: list[str] = Field(default_factory=list, max_length=4)

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('问题不能为空')
        return value.strip()

    @field_validator('previous_messages')
    @classmethod
    def bounded_history(cls, values):
        if any(not value.strip() or len(value) > 1000 for value in values):
            raise ValueError('每个前文问题应为 1 至 1000 字')
        return values


class PeriodArguments(StrictModel):
    period: Literal['DAY', 'WEEK', 'MONTH']
    window: Literal['CURRENT', 'PREVIOUS']


class FinishArguments(StrictModel):
    source_ids: list[str] = Field(min_length=1, max_length=6)
    compare: bool
