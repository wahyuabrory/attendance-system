from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal["check_in", "check_out"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class IdentityCreated(StrictModel):
    identity_id: UUID
    display_name: str | None
    image_count: int = Field(ge=2)
    created_at: datetime


class RecognitionResponse(StrictModel):
    decision: Literal["matched", "unknown", "ambiguous"]
    identity_id: UUID | None = None
    confirmation_token: str | None = None
    expires_at: datetime | None = None


class AttendanceConfirmation(StrictModel):
    confirmation_token: str = Field(min_length=1, max_length=4096)
    event_type: EventType


class AttendanceResponse(StrictModel):
    event_id: UUID
    identity_id: UUID | None
    event_type: EventType
    occurred_at: datetime
    created_at: datetime


class CorrectionRequest(StrictModel):
    event_type: EventType
    reason: str = Field(min_length=1, max_length=500)


class CorrectionResponse(StrictModel):
    correction_id: UUID
    event_id: UUID
    previous_event_type: EventType
    event_type: EventType
    reason: str
    created_at: datetime


class AttendanceHistoryItem(StrictModel):
    event_id: UUID
    identity_id: UUID | None
    event_type: EventType
    original_event_type: EventType
    occurred_at: datetime
    created_at: datetime
    corrected: bool


class AttendanceHistoryResponse(StrictModel):
    items: list[AttendanceHistoryItem]
    limit: int
    offset: int
    has_more: bool


class ErrorDetail(StrictModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(StrictModel):
    error: ErrorDetail
