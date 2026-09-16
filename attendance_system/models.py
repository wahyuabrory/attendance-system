from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .schemas import EventType

VECTOR_DIMENSION = 128


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class IdentityProfile(Base):
    __tablename__ = "identity_profiles"

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("now()")
    )
    embedding: Mapped[FaceEmbedding] = relationship(
        back_populates="identity", cascade="all, delete-orphan", uselist=False
    )


class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(VECTOR_DIMENSION), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("now()")
    )
    identity: Mapped[IdentityProfile] = relationship(back_populates="embedding")


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('check_in', 'check_out')", name="ck_attendance_event_type"),
        Index("ix_attendance_events_identity_occurred", "identity_id", "occurred_at"),
        Index("ix_attendance_events_occurred", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    identity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity_profiles.id", ondelete="SET NULL"), nullable=True
    )
    identity_display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    event_type: Mapped[EventType] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("now()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("now()")
    )


class AttendanceCorrection(Base):
    __tablename__ = "attendance_corrections"
    __table_args__ = (
        CheckConstraint(
            "previous_event_type IN ('check_in', 'check_out')", name="ck_correction_previous_type"
        ),
        CheckConstraint("event_type IN ('check_in', 'check_out')", name="ck_correction_event_type"),
        Index("ix_attendance_corrections_event_created", "event_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("attendance_events.id", ondelete="RESTRICT"), nullable=False
    )
    previous_event_type: Mapped[EventType] = mapped_column(String(16), nullable=False)
    event_type: Mapped[EventType] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    admin_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("now()")
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("now()")
    )
