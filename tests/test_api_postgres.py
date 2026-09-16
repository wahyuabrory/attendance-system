from __future__ import annotations

import os
from collections.abc import AsyncIterator
from io import BytesIO
from typing import Any

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from attendance_system.calibration import CalibrationArtifact
from attendance_system.config import Settings
from attendance_system.errors import AppError
from attendance_system.models import (
    AttendanceCorrection,
    AttendanceEvent,
    FaceEmbedding,
    IdempotencyRecord,
    IdentityProfile,
)
from attendance_system.security import TokenSigner
from attendance_system.services import AttendanceService, IdentityService, RecognitionService

ADMIN_KEY = "a" * 32
TERMINAL_KEY = "t" * 32
SIGNING_KEY = "s" * 32


class FakeInference:
    async def extract(self, image: Any) -> list[float]:
        first_pixel = tuple(int(channel) for channel in image[0, 0])
        if first_pixel == (0, 0, 0):
            raise AppError("no_face", "Exactly one face is required", 422)
        if first_pixel == (255, 255, 255):
            raise AppError("multiple_faces", "Exactly one face is required", 422)
        return [1.0] + [0.0] * 127


def png_bytes(color: tuple[int, int, int] = (20, 30, 40)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (160, 160), color=color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    database_url = os.getenv("ATTENDANCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("ATTENDANCE_TEST_DATABASE_URL is not set")
    from attendance_system.main import create_app

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as connection:
        extension = await connection.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        schema = await connection.scalar(text("SELECT to_regclass('identity_profiles')"))
    assert extension == "vector"
    assert schema == "identity_profiles"

    async with factory() as session, session.begin():
        for model in (
            AttendanceCorrection,
            IdempotencyRecord,
            AttendanceEvent,
            FaceEmbedding,
            IdentityProfile,
        ):
            await session.execute(delete(model))

    settings = Settings(
        database_url=database_url,
        admin_api_key=SecretStr(ADMIN_KEY),
        terminal_api_key=SecretStr(TERMINAL_KEY),
        token_signing_key=SecretStr(SIGNING_KEY),
    )
    app = create_app(settings)
    inference = FakeInference()
    signer = TokenSigner(SIGNING_KEY, ttl_seconds=60)
    app.state.session_factory = factory
    app.state.identity_service = IdentityService(inference)  # type: ignore[arg-type]
    app.state.recognition_service = RecognitionService(
        inference,  # type: ignore[arg-type]
        CalibrationArtifact(
            schema_version=1,
            threshold=0.8,
            ambiguity_margin=0.05,
            created_at="test",
        ),
        signer,
    )
    app.state.attendance_service = AttendanceService(signer)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await engine.dispose()


@pytest.mark.asyncio
async def test_attendance_lifecycle(api_client: httpx.AsyncClient) -> None:
    image = png_bytes()
    files = [("images", (f"sample-{index}.png", image, "image/png")) for index in range(3)]
    enrolled = await api_client.post(
        "/v1/identities",
        headers={"X-API-Key": ADMIN_KEY},
        data={"display_name": "Example Person"},
        files=files,
    )
    assert enrolled.status_code == 201, enrolled.text
    identity_id = enrolled.json()["identity_id"]

    recognized = await api_client.post(
        "/v1/recognitions",
        headers={"X-API-Key": TERMINAL_KEY},
        files={"image": ("sample.png", image, "image/png")},
    )
    assert recognized.status_code == 200, recognized.text
    assert recognized.json()["decision"] == "matched"

    attendance_body = {
        "confirmation_token": recognized.json()["confirmation_token"],
        "event_type": "check_in",
    }
    attendance = await api_client.post(
        "/v1/attendance",
        headers={"X-API-Key": TERMINAL_KEY, "Idempotency-Key": "terminal-request-1"},
        json=attendance_body,
    )
    assert attendance.status_code == 201, attendance.text
    event_id = attendance.json()["event_id"]
    repeated = await api_client.post(
        "/v1/attendance",
        headers={"X-API-Key": TERMINAL_KEY, "Idempotency-Key": "terminal-request-1"},
        json=attendance_body,
    )
    assert repeated.status_code == 200
    assert repeated.json()["event_id"] == event_id

    correction = await api_client.post(
        f"/v1/attendance/{event_id}/corrections",
        headers={"X-API-Key": ADMIN_KEY},
        json={"event_type": "check_out", "reason": "Operator selected the wrong event"},
    )
    assert correction.status_code == 201, correction.text
    history = await api_client.get("/v1/attendance", headers={"X-API-Key": ADMIN_KEY})
    assert history.json()["items"][0]["event_type"] == "check_out"
    assert history.json()["items"][0]["corrected"] is True

    removed = await api_client.delete(
        f"/v1/identities/{identity_id}", headers={"X-API-Key": ADMIN_KEY}
    )
    assert removed.status_code == 204
    anonymized = await api_client.get("/v1/attendance", headers={"X-API-Key": ADMIN_KEY})
    assert anonymized.json()["items"][0]["identity_id"] is None


@pytest.mark.asyncio
async def test_api_rejects_wrong_scope_and_ambiguous_match(
    api_client: httpx.AsyncClient,
) -> None:
    image = png_bytes()
    denied = await api_client.post(
        "/v1/identities",
        headers={"X-API-Key": TERMINAL_KEY},
        files=[("images", ("sample.png", image, "image/png"))] * 3,
    )
    assert denied.status_code == 401

    for name in ("First", "Second"):
        response = await api_client.post(
            "/v1/identities",
            headers={"X-API-Key": ADMIN_KEY},
            data={"display_name": name},
            files=[("images", ("sample.png", image, "image/png"))] * 3,
        )
        assert response.status_code == 201
    recognition = await api_client.post(
        "/v1/recognitions",
        headers={"X-API-Key": TERMINAL_KEY},
        files={"image": ("sample.png", image, "image/png")},
    )
    assert recognition.status_code == 200
    assert recognition.json() == {
        "decision": "ambiguous",
        "identity_id": None,
        "confirmation_token": None,
        "expires_at": None,
    }


@pytest.mark.asyncio
async def test_api_validates_authentication_uploads_and_safe_errors(
    api_client: httpx.AsyncClient,
) -> None:
    image = png_bytes()
    files = [("images", ("sample.png", image, "image/png"))] * 3

    unauthenticated = await api_client.post("/v1/identities", files=files)
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"]["code"] == "invalid_api_key"

    unsupported = await api_client.post(
        "/v1/identities",
        headers={"X-API-Key": ADMIN_KEY},
        files=[("images", ("sample.gif", b"not-an-image", "image/gif"))] * 3,
    )
    assert unsupported.status_code == 415
    assert unsupported.json()["error"]["code"] == "unsupported_image_type"

    for color, expected_code in (
        ((0, 0, 0), "no_face"),
        ((255, 255, 255), "multiple_faces"),
    ):
        recognition = await api_client.post(
            "/v1/recognitions",
            headers={"X-API-Key": TERMINAL_KEY},
            files={"image": ("sample.png", png_bytes(color), "image/png")},
        )
        assert recognition.status_code == 422
        assert recognition.json()["error"]["code"] == expected_code

    unknown = await api_client.post(
        "/v1/recognitions",
        headers={"X-API-Key": TERMINAL_KEY},
        files={"image": ("sample.png", image, "image/png")},
    )
    assert unknown.status_code == 200
    assert unknown.json()["decision"] == "unknown"

    health = await api_client.get("/healthz")
    assert health.status_code == 200
    assert health.headers["X-Request-ID"]

    readiness = await api_client.get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "not_ready"

    not_found = await api_client.get("/missing")
    assert not_found.status_code == 404
    assert not_found.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found",
            "request_id": not_found.headers["X-Request-ID"],
        }
    }

    method_not_allowed = await api_client.post("/healthz")
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.asyncio
async def test_api_rejects_bad_tokens_and_idempotency_conflicts(
    api_client: httpx.AsyncClient,
) -> None:
    image = png_bytes()
    enrolled = await api_client.post(
        "/v1/identities",
        headers={"X-API-Key": ADMIN_KEY},
        data={"display_name": "Example Person"},
        files=[("images", ("sample.png", image, "image/png"))] * 3,
    )
    assert enrolled.status_code == 201, enrolled.text
    identity_id = enrolled.json()["identity_id"]

    recognized = await api_client.post(
        "/v1/recognitions",
        headers={"X-API-Key": TERMINAL_KEY},
        files={"image": ("sample.png", image, "image/png")},
    )
    assert recognized.status_code == 200, recognized.text
    token = recognized.json()["confirmation_token"]

    invalid_token = await api_client.post(
        "/v1/attendance",
        headers={"X-API-Key": TERMINAL_KEY, "Idempotency-Key": "invalid-token"},
        json={"confirmation_token": token + "x", "event_type": "check_in"},
    )
    assert invalid_token.status_code == 401
    assert invalid_token.json()["error"]["code"] == "invalid_confirmation_token"

    body = {"confirmation_token": token, "event_type": "check_in"}
    created = await api_client.post(
        "/v1/attendance",
        headers={"X-API-Key": TERMINAL_KEY, "Idempotency-Key": "conflict-check"},
        json=body,
    )
    assert created.status_code == 201, created.text

    conflict = await api_client.post(
        "/v1/attendance",
        headers={"X-API-Key": TERMINAL_KEY, "Idempotency-Key": "conflict-check"},
        json={"confirmation_token": token, "event_type": "check_out"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_reused"

    filtered = await api_client.get(
        "/v1/attendance",
        headers={"X-API-Key": ADMIN_KEY},
        params={"identity_id": identity_id, "event_type": "check_in", "limit": 1},
    )
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["items"][0]["identity_id"] == identity_id

    invalid_range = await api_client.get(
        "/v1/attendance",
        headers={"X-API-Key": ADMIN_KEY},
        params={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    )
    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "invalid_time_range"

    invalid_reason = await api_client.post(
        f"/v1/attendance/{created.json()['event_id']}/corrections",
        headers={"X-API-Key": ADMIN_KEY},
        json={"event_type": "check_out", "reason": "invalid\u0000reason"},
    )
    assert invalid_reason.status_code == 422
    assert invalid_reason.json()["error"]["code"] == "invalid_reason"

    removed = await api_client.delete(
        f"/v1/identities/{identity_id}", headers={"X-API-Key": ADMIN_KEY}
    )
    assert removed.status_code == 204

    anonymized_retry = await api_client.post(
        "/v1/attendance",
        headers={"X-API-Key": TERMINAL_KEY, "Idempotency-Key": "conflict-check"},
        json=body,
    )
    assert anonymized_retry.status_code == 200
    assert anonymized_retry.json()["identity_id"] is None
