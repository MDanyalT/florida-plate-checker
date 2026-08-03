"""Pydantic request and response schemas used by JSON endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RunProgress(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_candidates: int
    checked_count: int
    available_count: int
    unavailable_count: int
    invalid_count: int
    unknown_count: int
    error_count: int
    current_batch: int
    last_processed_plate: str | None = None
    error_message: str | None = None


class NotesUpdate(BaseModel):
    notes: str = Field(max_length=2000)

