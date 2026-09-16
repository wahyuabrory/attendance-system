from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in ("request_id", "status_code", "duration_ms", "error_code", "error_type"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = True
    access_logger.handlers.clear()
    access_logger.propagate = False
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


logger = logging.getLogger("attendance_system")


def request_id_from(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "")
    if supplied and len(supplied) <= 64 and all(c.isalnum() or c in "._-" for c in supplied):
        return supplied
    return str(uuid.uuid4())


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request_id_from(request)
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        extra: dict[str, Any] = {
            "event": "request.complete",
            "request_id": request_id,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
        error_code = getattr(request.state, "error_code", None)
        if error_code is not None:
            extra["error_code"] = error_code
        logger.info("request complete", extra=extra)
        return response
