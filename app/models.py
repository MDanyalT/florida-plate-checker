"""SQLAlchemy models for plates, immutable history, and checking runs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Plate(Base):
    __tablename__ = "plates"
    __table_args__ = (UniqueConstraint("normalized_plate", name="uq_plates_normalized_plate"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_plate: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    raw_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    check_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    history: Mapped[list[CheckHistory]] = relationship(
        back_populates="plate", cascade="all, delete-orphan"
    )


class CheckingRun(Base):
    __tablename__ = "checking_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    total_candidates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unavailable_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_batch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    batches_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    captcha_pause_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_processed_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def active_processing_seconds(self) -> float:
        return max(0.0, self.elapsed_seconds - self.captcha_pause_seconds)

    @property
    def average_seconds_per_plate(self) -> float:
        if not self.checked_count:
            return 0.0
        return self.active_processing_seconds / self.checked_count

    history: Mapped[list[CheckHistory]] = relationship(back_populates="run")


class CheckHistory(Base):
    __tablename__ = "check_history"
    __table_args__ = (
        Index("ix_check_history_plate_checked", "plate_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate_id: Mapped[int] = mapped_column(
        ForeignKey("plates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    raw_result: Mapped[str] = mapped_column(Text, default="", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )
    batch_number: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("checking_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    plate: Mapped[Plate] = relationship(back_populates="history")
    run: Mapped[CheckingRun | None] = relationship(back_populates="history")
