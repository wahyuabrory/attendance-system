FROM ghcr.io/astral-sh/uv:0.11.14 AS build

WORKDIR /build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY .python-version pyproject.toml uv.lock README.md ./
COPY attendance_system ./attendance_system
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN uv sync --frozen --no-dev
RUN uv run attendance-system download-models --directory /opt/models

FROM python:3.12.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    ATTENDANCE_MODEL_DIR=/opt/models
RUN apt-get update \
    && apt-get install --no-install-recommends -y libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /build/.venv /app/.venv
COPY --from=build /build/attendance_system /app/attendance_system
COPY --from=build /build/alembic.ini /app/alembic.ini
COPY --from=build /build/alembic /app/alembic
COPY --from=build /opt/models /opt/models
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app /opt/models
USER app
EXPOSE 8000
CMD ["uvicorn", "attendance_system.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
