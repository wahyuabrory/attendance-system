"""Create the attendance schema.

Revision ID: 0001_initial
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "identity_profiles",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "face_embeddings",
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column("embedding", Vector(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["identity_id"], ["identity_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("identity_id"),
    )
    op.create_table(
        "attendance_events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=True),
        sa.Column("identity_display_name", sa.String(length=100), nullable=True),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('check_in', 'check_out')", name="ck_attendance_event_type"
        ),
        sa.ForeignKeyConstraint(["identity_id"], ["identity_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_events_identity_occurred",
        "attendance_events",
        ["identity_id", "occurred_at"],
    )
    op.create_index("ix_attendance_events_occurred", "attendance_events", ["occurred_at"])
    op.create_table(
        "attendance_corrections",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("previous_event_type", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("admin_key_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "previous_event_type IN ('check_in', 'check_out')", name="ck_correction_previous_type"
        ),
        sa.CheckConstraint(
            "event_type IN ('check_in', 'check_out')", name="ck_correction_event_type"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["attendance_events.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attendance_corrections_event_created",
        "attendance_corrections",
        ["event_id", "created_at"],
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("ix_attendance_corrections_event_created", table_name="attendance_corrections")
    op.drop_table("attendance_corrections")
    op.drop_index("ix_attendance_events_occurred", table_name="attendance_events")
    op.drop_index("ix_attendance_events_identity_occurred", table_name="attendance_events")
    op.drop_table("attendance_events")
    op.drop_table("face_embeddings")
    op.drop_table("identity_profiles")
