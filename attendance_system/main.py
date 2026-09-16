from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser

from .api import router
from .calibration import load_calibration
from .config import Settings, get_settings
from .db import create_engine, create_session_factory, database_ready
from .errors import AppError, RuntimeConfigError
from .inference import InferenceService, ModelBundle
from .observability import RequestLoggingMiddleware, configure_logging, logger
from .schemas import ErrorDetail, ErrorResponse
from .security import TokenSigner
from .services import AttendanceService, IdentityService, RecognitionService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.validate_for_api()
    configure_logging()
    calibration = load_calibration(settings.calibration_path, settings.environment == "production")
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    bundle = ModelBundle(settings)
    inference = InferenceService(bundle, settings.inference_concurrency)
    if settings.token_signing_key is None:
        raise RuntimeConfigError("ATTENDANCE_TOKEN_SIGNING_KEY must be set")
    signer = TokenSigner(
        settings.token_signing_key.get_secret_value(), settings.confirmation_ttl_seconds
    )
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.model_bundle = bundle
    app.state.identity_service = IdentityService(inference)
    app.state.recognition_service = RecognitionService(inference, calibration, signer)
    app.state.attendance_service = AttendanceService(signer)
    yield
    await engine.dispose()


def _error_response(request: Request, code: str, message: str, status_code: int) -> JSONResponse:
    request.state.error_code = code
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=ErrorDetail(code=code, message=message, request_id=request_id)
        ).model_dump(mode="json"),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    # Keep biometric uploads in memory to prevent their content reaching disk.
    MultiPartParser.spool_max_size = 0
    app = FastAPI(
        title="Attendance system API",
        version="0.1.0",
        description=(
            "A source-only reference service for explicit attendance events after "
            "face recognition confirmation."
        ),
        lifespan=lifespan,
        responses={
            400: {"model": ErrorResponse},
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            405: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            500: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    app.state.settings = app_settings
    app.add_middleware(RequestLoggingMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
        return _error_response(request, error.code, error.message, error.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        if error.status_code == 404:
            code, message = "not_found", "The requested resource was not found"
        elif error.status_code == 405:
            code, message = "method_not_allowed", "The requested method is not allowed"
        else:
            code, message = "http_error", "The request could not be completed"
        return _error_response(request, code, message, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return _error_response(request, "invalid_request", "Request validation failed", 422)

    @app.exception_handler(RuntimeConfigError)
    async def config_error_handler(request: Request, _error: RuntimeConfigError) -> JSONResponse:
        return _error_response(
            request, "configuration_error", "Service configuration is invalid", 500
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
        logger.exception(
            "unexpected request error",
            extra={
                "event": "request.unexpected",
                "error_code": "internal_error",
                "error_type": type(error).__name__,
            },
        )
        return _error_response(
            request, "internal_error", "The service could not complete the request", 500
        )

    @app.get("/healthz", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    async def readiness(request: Request) -> JSONResponse:
        checks: dict[str, str] = {"database": "failed", "models": "failed", "calibration": "failed"}
        factory = getattr(request.app.state, "session_factory", None)
        if factory is not None and await database_ready(factory):
            checks["database"] = "ok"
        bundle = getattr(request.app.state, "model_bundle", None)
        if bundle is not None and await asyncio.to_thread(bundle.ready):
            checks["models"] = "ok"
        settings: Settings = request.app.state.settings
        try:
            load_calibration(settings.calibration_path, settings.environment == "production")
            checks["calibration"] = "ok"
        except RuntimeConfigError:
            pass
        ready = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": checks},
        )

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("attendance_system.main:app", host="0.0.0.0", port=8000)
