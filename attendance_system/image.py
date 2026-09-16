from __future__ import annotations

from io import BytesIO
from typing import Final

import cv2
import numpy as np
from fastapi import UploadFile
from PIL import Image

from .config import Settings
from .errors import AppError

JPEG: Final = "image/jpeg"
PNG: Final = "image/png"
_ALLOWED_TYPES: Final = {JPEG, PNG}


async def decode_upload(upload: UploadFile, settings: Settings) -> np.ndarray:
    if upload.content_type not in _ALLOWED_TYPES:
        raise AppError("unsupported_image_type", "Only JPEG and PNG images are accepted", 415)
    content = await upload.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise AppError("image_too_large", "Image exceeds the configured size limit", 413)
    if not content:
        raise AppError("invalid_image", "Image could not be decoded", 400)

    try:
        with Image.open(BytesIO(content)) as source:
            expected_format = "JPEG" if upload.content_type == JPEG else "PNG"
            if source.format != expected_format:
                raise AppError(
                    "invalid_image", "Image content does not match its declared type", 400
                )
            width, height = source.size
            _validate_dimensions(width, height, settings)
            source.load()
            rgb = np.asarray(source.convert("RGB"), dtype=np.uint8)
    except AppError:
        raise
    except (Image.DecompressionBombError, OSError, ValueError):
        raise AppError("invalid_image", "Image could not be decoded", 400) from None
    decoded = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return decoded


def _validate_dimensions(width: int, height: int, settings: Settings) -> None:
    if width < settings.min_image_dimension or height < settings.min_image_dimension:
        raise AppError("image_resolution_too_low", "Image resolution is below the minimum", 400)
    if width > settings.max_image_dimension or height > settings.max_image_dimension:
        raise AppError("image_resolution_too_high", "Image dimensions exceed the limit", 413)
    if width * height > settings.max_image_pixels:
        raise AppError("image_resolution_too_high", "Image pixel count exceeds the limit", 413)


def validate_display_name(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    if not result or len(result) > 100:
        raise AppError("invalid_display_name", "Display name must contain 1 to 100 characters", 422)
    if any(ord(char) < 32 for char in result):
        raise AppError("invalid_display_name", "Display name contains a control character", 422)
    return result
