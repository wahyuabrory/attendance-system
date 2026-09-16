from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AttendanceCorrection,
    AttendanceEvent,
    FaceEmbedding,
    IdempotencyRecord,
    IdentityProfile,
)


async def find_identity(session: AsyncSession, identity_id: UUID) -> IdentityProfile | None:
    return await session.get(IdentityProfile, identity_id)


async def find_matches(
    session: AsyncSession, embedding: list[float], limit: int = 2
) -> list[tuple[UUID, float]]:
    distance = FaceEmbedding.embedding.cosine_distance(embedding)
    statement = (
        select(FaceEmbedding.identity_id, (1 - distance).label("score"))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()
    return [(row.identity_id, float(row.score)) for row in rows]


async def latest_correction(session: AsyncSession, event_id: UUID) -> AttendanceCorrection | None:
    statement = (
        select(AttendanceCorrection)
        .where(AttendanceCorrection.event_id == event_id)
        .order_by(desc(AttendanceCorrection.created_at), desc(AttendanceCorrection.id))
        .limit(1)
    )
    return (await session.execute(statement)).scalar_one_or_none()


async def history_query(
    session: AsyncSession,
    identity_id: UUID | None,
    event_type: str | None,
    from_time: datetime | None,
    to_time: datetime | None,
    limit: int,
    offset: int,
) -> list[tuple[AttendanceEvent, AttendanceCorrection | None]]:
    statement = (
        select(AttendanceEvent)
        .order_by(desc(AttendanceEvent.occurred_at), desc(AttendanceEvent.id))
        .limit(limit)
        .offset(offset)
    )
    if identity_id is not None:
        statement = statement.where(AttendanceEvent.identity_id == identity_id)
    if event_type is not None:
        statement = statement.where(AttendanceEvent.event_type == event_type)
    if from_time is not None:
        statement = statement.where(AttendanceEvent.occurred_at >= from_time)
    if to_time is not None:
        statement = statement.where(AttendanceEvent.occurred_at < to_time)
    events = list((await session.execute(statement)).scalars())
    if not events:
        return []
    corrections = (
        await session.execute(
            select(AttendanceCorrection)
            .where(AttendanceCorrection.event_id.in_([event.id for event in events]))
            .order_by(desc(AttendanceCorrection.created_at), desc(AttendanceCorrection.id))
        )
    ).scalars()
    latest: dict[UUID, AttendanceCorrection] = {}
    for correction in corrections:
        latest.setdefault(correction.event_id, correction)
    return [(event, latest.get(event.id)) for event in events]


async def get_idempotency(session: AsyncSession, scope: str, key: str) -> IdempotencyRecord | None:
    statement = select(IdempotencyRecord).where(
        IdempotencyRecord.scope == scope, IdempotencyRecord.key == key
    )
    return (await session.execute(statement)).scalar_one_or_none()
