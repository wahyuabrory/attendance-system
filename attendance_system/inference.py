from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from .config import Settings
from .errors import AppError
from .model_download import MODEL_SPECS, verify_models
from .observability import logger


@dataclass(frozen=True, slots=True)
class DetectedFace:
    raw: np.ndarray
    x: float
    y: float
    width: float
    height: float


class Detector(Protocol):
    def detect(self, image: np.ndarray) -> list[DetectedFace]: ...


class Encoder(Protocol):
    def encode(self, image: np.ndarray, face: DetectedFace) -> np.ndarray: ...


class YuNetDetector:
    def __init__(self, model_path: Path, settings: Settings) -> None:
        self._model_path = model_path
        self._settings = settings
        self._detector: cv2.FaceDetectorYN | None = None

    def _loaded(self) -> cv2.FaceDetectorYN:
        if self._detector is None:
            if not self._model_path.is_file():
                raise RuntimeError("YuNet model is missing")
            self._detector = cv2.FaceDetectorYN.create(
                str(self._model_path),
                "",
                (320, 320),
                self._settings.detector_score_threshold,
                self._settings.detector_nms_threshold,
                self._settings.detector_top_k,
            )
        return self._detector

    def detect(self, image: np.ndarray) -> list[DetectedFace]:
        detector = self._loaded()
        height, width = image.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(image)
        if faces is None:
            return []
        return [
            DetectedFace(
                raw=np.asarray(row, dtype=np.float32),
                x=float(row[0]),
                y=float(row[1]),
                width=float(row[2]),
                height=float(row[3]),
            )
            for row in faces
        ]


class SFaceEncoder:
    def __init__(self, model_path: Path) -> None:
        self._model_path = model_path
        self._recognizer: cv2.FaceRecognizerSF | None = None

    def _loaded(self) -> cv2.FaceRecognizerSF:
        if self._recognizer is None:
            if not self._model_path.is_file():
                raise RuntimeError("SFace model is missing")
            self._recognizer = cv2.FaceRecognizerSF.create(str(self._model_path), "")
        return self._recognizer

    def encode(self, image: np.ndarray, face: DetectedFace) -> np.ndarray:
        recognizer = self._loaded()
        aligned = recognizer.alignCrop(image, face.raw.reshape(1, -1))
        return np.asarray(recognizer.feature(aligned), dtype=np.float32).reshape(-1)


class ModelBundle:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._detector = YuNetDetector(settings.model_dir / MODEL_SPECS["yunet"].filename, settings)
        self._encoder = SFaceEncoder(settings.model_dir / MODEL_SPECS["sface"].filename)
        self._loaded = False

    @property
    def detector(self) -> Detector:
        return self._detector

    @property
    def encoder(self) -> Encoder:
        return self._encoder

    def load(self) -> None:
        if self._loaded:
            return
        errors = verify_models(self._settings.model_dir)
        if errors:
            raise RuntimeError("; ".join(errors))
        self._detector._loaded()
        self._encoder._loaded()
        self._loaded = True

    def ready(self) -> bool:
        try:
            self.load()
        except Exception as error:
            logger.exception(
                "model readiness failed",
                extra={
                    "event": "model.readiness.failed",
                    "error_code": "model_readiness_failed",
                    "error_type": type(error).__name__,
                },
            )
            return False
        return True


class InferenceService:
    def __init__(self, bundle: ModelBundle, concurrency: int) -> None:
        self._bundle = bundle
        self._slots = asyncio.Semaphore(concurrency)

    @staticmethod
    def _extract(detector: Detector, encoder: Encoder, image: np.ndarray) -> list[float]:
        faces = detector.detect(image)
        if not faces:
            raise AppError("no_face", "Exactly one face is required", 422)
        if len(faces) > 1:
            raise AppError("multiple_faces", "Exactly one face is required", 422)
        embedding = normalize_embedding(encoder.encode(image, faces[0]))
        return embedding

    async def extract(self, image: np.ndarray) -> list[float]:
        try:
            async with self._slots:
                self._bundle.load()
                return await asyncio.to_thread(
                    self._extract, self._bundle.detector, self._bundle.encoder, image
                )
        except AppError:
            raise
        except Exception as error:
            logger.exception(
                "inference failed",
                extra={
                    "event": "inference.failed",
                    "error_code": "inference_unavailable",
                    "error_type": type(error).__name__,
                },
            )
            raise AppError("inference_unavailable", "Face processing is unavailable", 503) from None


def normalize_embedding(values: np.ndarray | list[float]) -> list[float]:
    array = np.asarray(values, dtype=np.float32).reshape(-1)
    if array.size == 0 or not np.isfinite(array).all():
        raise AppError("invalid_embedding", "Face processing produced an invalid embedding", 422)
    norm = float(np.linalg.norm(array))
    if norm <= 1e-8:
        raise AppError("invalid_embedding", "Face processing produced an invalid embedding", 422)
    return [float(item) for item in array / norm]


def aggregate_embeddings(embeddings: list[list[float]]) -> list[float]:
    if not embeddings:
        raise ValueError("at least one embedding is required")
    normalized = np.asarray([normalize_embedding(item) for item in embeddings], dtype=np.float32)
    return normalize_embedding(normalized.mean(axis=0))
