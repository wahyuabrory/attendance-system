from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .errors import RuntimeConfigError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ATTENDANCE_",
        extra="forbid",
        case_sensitive=False,
    )

    environment: Literal["development", "production"] = "development"
    database_url: str
    admin_api_key: SecretStr | None = None
    terminal_api_key: SecretStr | None = None
    token_signing_key: SecretStr | None = None
    model_dir: Path = Path("models")
    calibration_path: Path | None = None
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024)
    max_image_pixels: int = Field(default=12_000_000, ge=1, le=50_000_000)
    max_image_dimension: int = Field(default=4096, ge=64, le=16_384)
    min_image_dimension: int = Field(default=160, ge=32, le=4096)
    enrollment_min_images: int = Field(default=3, ge=2, le=8)
    enrollment_max_images: int = Field(default=8, ge=2, le=8)
    detector_score_threshold: float = Field(default=0.9, gt=0, le=1)
    detector_nms_threshold: float = Field(default=0.3, gt=0, le=1)
    detector_top_k: int = Field(default=5000, ge=1, le=20_000)
    confirmation_ttl_seconds: int = Field(default=60, ge=15, le=300)
    inference_concurrency: int = Field(default=1, ge=1, le=4)

    @field_validator("calibration_path", mode="before")
    @classmethod
    def blank_calibration_is_unset(cls, value: Any) -> Any:
        return None if value == "" else value

    def validate_for_api(self) -> None:
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise RuntimeConfigError("ATTENDANCE_DATABASE_URL must use postgresql+asyncpg")
        if self.enrollment_min_images > self.enrollment_max_images:
            raise RuntimeConfigError("enrollment image limits are invalid")
        if self.environment == "production" and self.calibration_path is None:
            raise RuntimeConfigError("ATTENDANCE_CALIBRATION_PATH is required in production")
        values: dict[str, str] = {}
        for name, secret in (
            ("ATTENDANCE_ADMIN_API_KEY", self.admin_api_key),
            ("ATTENDANCE_TERMINAL_API_KEY", self.terminal_api_key),
            ("ATTENDANCE_TOKEN_SIGNING_KEY", self.token_signing_key),
        ):
            if secret is None:
                raise RuntimeConfigError(f"{name} must contain at least 32 characters")
            value = secret.get_secret_value()
            if len(value) < 32:
                raise RuntimeConfigError(f"{name} must contain at least 32 characters")
            if self.environment == "production" and value.startswith("replace-with-"):
                raise RuntimeConfigError(f"{name} must be replaced in production")
            values[name] = value

        if values["ATTENDANCE_ADMIN_API_KEY"] == values["ATTENDANCE_TERMINAL_API_KEY"]:
            raise RuntimeConfigError(
                "ATTENDANCE_ADMIN_API_KEY and ATTENDANCE_TERMINAL_API_KEY must differ"
            )
        if values["ATTENDANCE_TOKEN_SIGNING_KEY"] in {
            values["ATTENDANCE_ADMIN_API_KEY"],
            values["ATTENDANCE_TERMINAL_API_KEY"],
        }:
            raise RuntimeConfigError(
                "ATTENDANCE_TOKEN_SIGNING_KEY must differ from ATTENDANCE_ADMIN_API_KEY "
                "and ATTENDANCE_TERMINAL_API_KEY"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
