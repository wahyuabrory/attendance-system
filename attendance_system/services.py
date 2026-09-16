from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from numpy import ndarray
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .calibration import CalibrationArtifact
from .errors import AppError
from .inference import InferenceService, aggregate_embeddings
from .models import (
    AttendanceCorrection,
    AttendanceEvent,
    FaceEmbedding,
    IdempotencyRecord,
    IdentityProfile,
)
from .repositories import (
    find_identity,
    find_matches,
    get_idempotency,
    history_query,
    latest_correction,
)
from .schemas import (
    AttendanceHistoryItem,
    AttendanceResponse,
    CorrectionResponse,
    EventType,
    IdentityCreated,
    RecognitionResponse,
)
from .security import Principal, TokenSigner


class IdentityService:
    def __init__(self, inference: InferenceService) -> None:
        self._inference = inference

    async def enroll(
        self, session: AsyncSession, display_name: str | None, images: list[ndarray]
    ) -> IdentityCreated:
        embeddings = [await self._inference.extract(image) for image in images]
        aggregate = aggregate_embeddings(embeddings)
        identity = IdentityProfile(id=uuid4(), display_name=display_name)
        session.add(identity)
        session.add(FaceEmbedding(identity_id=identity.id, embedding=aggregate))
        await session.flush()
        return IdentityCreated(
            identity_id=identity.id,
            display_name=identity.display_name,
            image_count=len(images),
            created_at=identity.created_at,
        )


class RecognitionService:
    def __init__(
        self, inference: InferenceService, calibration: CalibrationArtifact, signer: TokenSigner
    ) -> None:
        self._inference = inference
        self._calibration = calibration
        self._signer = signer

    async def recognize(self, session: AsyncSession, image: ndarray) -> RecognitionResponse:
        embedding = await self._inference.extract(image)
        candidates = await find_matches(session, embedding)
        if not candidates or candidates[0][1] < self._calibration.threshold:
            return RecognitionResponse(decision="unknown")
        if (
            len(candidates) > 1
            and candidates[0][1] - candidates[1][1] < self._calibration.ambiguity_margin
        ):
            return RecognitionResponse(decision="ambiguous")
        identity_id = candidates[0][0]
        token, expires_at = self._signer.issue(identity_id)
        return RecognitionResponse(
            decision="matched",
            identity_id=identity_id,
            confirmation_token=token,
            expires_at=expires_at,
        )


class AttendanceService:
    def __init__(self, signer: TokenSigner) -> None:
        self._signer = signer

    @staticmethod
    def _fingerprint(token: str, event_type: EventType) -> str:
        return hashlib.sha256(f"{token}\0{event_type}".encode()).hexdigest()

    async def confirm(
        self,
        session: AsyncSession,
        token: str,
        event_type: EventType,
        idempotency_key: str,
    ) -> tuple[AttendanceResponse, int]:
        fingerprint = self._fingerprint(token, event_type)
        existing = await get_idempotency(session, "attendance", idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise AppError(
                    "idempotency_key_reused", "Idempotency key was used for another request", 409
                )
            return AttendanceResponse.model_validate_json(json.dumps(existing.response)), 200

        confirmation = self._signer.verify(token)
        inserted = await session.execute(
            insert(IdempotencyRecord)
            .values(
                id=uuid4(),
                scope="attendance",
                key=idempotency_key,
                request_fingerprint=fingerprint,
                response={},
            )
            .on_conflict_do_nothing(index_elements=["scope", "key"])
            .returning(IdempotencyRecord.id)
        )
        inserted_id = inserted.scalar_one_or_none()
        if inserted_id is None:
            existing = await get_idempotency(session, "attendance", idempotency_key)
            if existing is None or existing.request_fingerprint != fingerprint:
                raise AppError(
                    "idempotency_conflict", "Attendance request could not be completed", 409
                )
            return AttendanceResponse.model_validate_json(json.dumps(existing.response)), 200

        identity = await find_identity(session, confirmation.identity_id)
        if identity is None:
            raise AppError("identity_not_found", "Identity is no longer available", 410)
        event = AttendanceEvent(
            id=uuid4(),
            identity_id=identity.id,
            identity_display_name=identity.display_name,
            event_type=event_type,
        )
        session.add(event)
        await session.flush()
        response = AttendanceResponse(
            event_id=event.id,
            identity_id=identity.id,
            event_type=event_type,
            occurred_at=event.occurred_at,
            created_at=event.created_at,
        )
        record = await session.get(IdempotencyRecord, inserted_id)
        if record is None:
            raise AppError("idempotency_conflict", "Attendance request could not be completed", 409)
        record.response = json.loads(response.model_dump_json())
        return response, 201

    async def correct(
        self,
        session: AsyncSession,
        event_id: UUID,
        event_type: EventType,
        reason: str,
        principal: Principal,
    ) -> CorrectionResponse:
        event = await session.get(AttendanceEvent, event_id)
        if event is None:
            raise AppError("attendance_not_found", "Attendance event was not found", 404)
        previous = (await latest_correction(session, event_id)) or event
        correction = AttendanceCorrection(
            id=uuid4(),
            event_id=event_id,
            previous_event_type=previous.event_type,
            event_type=event_type,
            reason=reason,
            admin_key_fingerprint=principal.fingerprint,
        )
        session.add(correction)
        await session.flush()
        return CorrectionResponse(
            correction_id=correction.id,
            event_id=event_id,
            previous_event_type=previous.event_type,
            event_type=event_type,
            reason=reason,
            created_at=correction.created_at,
        )

    async def history(
        self,
        session: AsyncSession,
        identity_id: UUID | None,
        event_type: EventType | None,
        from_time: datetime | None,
        to_time: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AttendanceHistoryItem], bool]:
        rows = await history_query(
            session, identity_id, event_type, from_time, to_time, limit + 1, offset
        )
        has_more = len(rows) > limit
        items = []
        for event, correction in rows[:limit]:
            items.append(
                AttendanceHistoryItem(
                    event_id=event.id,
                    identity_id=event.identity_id,
                    event_type=correction.event_type if correction else event.event_type,
                    original_event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    created_at=event.created_at,
                    corrected=correction is not None,
                )
            )
        return items, has_more


async def delete_identity(session: AsyncSession, identity_id: UUID) -> None:
    identity = await find_identity(session, identity_id)
    if identity is None:
        raise AppError("identity_not_found", "Identity was not found", 404)
    records = (
        (
            await session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == "attendance",
                    IdempotencyRecord.response["identity_id"].as_string() == str(identity_id),
                )
            )
        )
        .scalars()
        .all()
    )
    for record in records:
        response = dict(record.response)
        response["identity_id"] = None
        record.response = response

    await session.execute(
        update(AttendanceEvent)
        .where(AttendanceEvent.identity_id == identity_id)
        .values(identity_id=None, identity_display_name=None)
    )
    await session.delete(identity)
    await session.flush()
