from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .db import session_dependency
from .errors import AppError
from .image import decode_upload, validate_display_name
from .observability import logger
from .schemas import (
    AttendanceConfirmation,
    AttendanceHistoryResponse,
    AttendanceResponse,
    CorrectionRequest,
    CorrectionResponse,
    EventType,
    IdentityCreated,
    RecognitionResponse,
)
from .security import Principal, authenticate
from .services import AttendanceService, IdentityService, RecognitionService, delete_identity

router = APIRouter(prefix="/v1")


def settings_from(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def session_from(request: Request) -> AsyncIterator[AsyncSession]:
    return session_dependency(request.app.state.session_factory)


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in session_from(request):
        yield session


def require_scope(scope: Literal["admin", "terminal"]) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        request: Request,
        api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> Principal:
        settings = settings_from(request)
        secret = settings.admin_api_key if scope == "admin" else settings.terminal_api_key
        if secret is None:
            raise AppError("authentication_unavailable", "Authentication is not configured", 503)
        return authenticate(api_key, secret.get_secret_value(), scope)

    return dependency


Admin = Annotated[Principal, Depends(require_scope("admin"))]
Terminal = Annotated[Principal, Depends(require_scope("terminal"))]
Session = Annotated[AsyncSession, Depends(database_session)]


@router.post("/identities", response_model=IdentityCreated, status_code=201)
async def enroll_identity(
    request: Request,
    session: Session,
    _admin: Admin,
    images: Annotated[list[UploadFile], File(...)],
    display_name: Annotated[str | None, Form()] = None,
) -> IdentityCreated:
    settings = settings_from(request)
    if not settings.enrollment_min_images <= len(images) <= settings.enrollment_max_images:
        raise AppError(
            "invalid_image_count",
            (
                f"Enrollment requires {settings.enrollment_min_images} to "
                f"{settings.enrollment_max_images} images"
            ),
            422,
        )
    decoded = [await decode_upload(image, settings) for image in images]
    service: IdentityService = request.app.state.identity_service
    try:
        async with session.begin():
            result = await service.enroll(session, validate_display_name(display_name), decoded)
    except AppError:
        raise
    except Exception as error:
        logger.exception(
            "enrollment failed",
            extra={
                "event": "enrollment.failed",
                "error_code": "enrollment_failed",
                "error_type": type(error).__name__,
            },
        )
        raise AppError("enrollment_failed", "Enrollment could not be completed", 500) from None
    return result


@router.post("/recognitions", response_model=RecognitionResponse)
async def recognize(
    request: Request,
    session: Session,
    _terminal: Terminal,
    image: Annotated[UploadFile, File(...)],
) -> RecognitionResponse:
    decoded = await decode_upload(image, settings_from(request))
    service: RecognitionService = request.app.state.recognition_service
    return await service.recognize(session, decoded)


@router.post("/attendance", response_model=AttendanceResponse)
async def confirm_attendance(
    request: Request,
    session: Session,
    _terminal: Terminal,
    body: AttendanceConfirmation,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    if idempotency_key is None or not 1 <= len(idempotency_key) <= 255:
        raise AppError(
            "missing_idempotency_key", "Idempotency-Key must contain 1 to 255 characters", 400
        )
    if any(ord(char) < 32 for char in idempotency_key):
        raise AppError(
            "invalid_idempotency_key", "Idempotency-Key contains a control character", 400
        )
    service: AttendanceService = request.app.state.attendance_service
    async with session.begin():
        result, status_code = await service.confirm(
            session, body.confirmation_token, body.event_type, idempotency_key
        )
    return JSONResponse(status_code=status_code, content=result.model_dump(mode="json"))


@router.get("/attendance", response_model=AttendanceHistoryResponse)
async def attendance_history(
    request: Request,
    session: Session,
    _admin: Admin,
    identity_id: UUID | None = Query(default=None),
    event_type: EventType | None = Query(default=None),
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
) -> AttendanceHistoryResponse:
    if from_time and to_time and from_time >= to_time:
        raise AppError("invalid_time_range", "from must be earlier than to", 422)
    service: AttendanceService = request.app.state.attendance_service
    items, has_more = await service.history(
        session, identity_id, event_type, from_time, to_time, limit, offset
    )
    return AttendanceHistoryResponse(items=items, limit=limit, offset=offset, has_more=has_more)


@router.post(
    "/attendance/{event_id}/corrections", response_model=CorrectionResponse, status_code=201
)
async def correct_attendance(
    request: Request,
    session: Session,
    admin: Admin,
    event_id: UUID,
    body: CorrectionRequest,
) -> CorrectionResponse:
    if any(ord(char) < 32 for char in body.reason):
        raise AppError("invalid_reason", "Correction reason contains a control character", 422)
    reason = body.reason.strip()
    if not reason:
        raise AppError("invalid_reason", "Correction reason must not be blank", 422)
    service: AttendanceService = request.app.state.attendance_service
    async with session.begin():
        return await service.correct(session, event_id, body.event_type, reason, admin)


@router.delete("/identities/{identity_id}", status_code=204)
async def remove_identity(
    session: Session,
    _admin: Admin,
    identity_id: UUID,
) -> None:
    async with session.begin():
        await delete_identity(session, identity_id)
