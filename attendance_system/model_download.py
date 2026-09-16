from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    filename: str
    url: str
    sha256: str


# These are immutable OpenCV Zoo Git LFS objects at one repository revision.
MODEL_SPECS: dict[str, ModelSpec] = {
    "yunet": ModelSpec(
        name="YuNet face detector",
        filename="face_detection_yunet_2023mar.onnx",
        url="https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "sface": ModelSpec(
        name="SFace face encoder",
        filename="face_recognition_sface_2021dec.onnx",
        url="https://media.githubusercontent.com/media/opencv/opencv_zoo/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_models(directory: Path) -> list[str]:
    errors: list[str] = []
    for spec in MODEL_SPECS.values():
        path = directory / spec.filename
        if not path.is_file():
            errors.append(f"missing {spec.filename}")
        elif _digest(path) != spec.sha256:
            errors.append(f"checksum mismatch for {spec.filename}")
    return errors


def download_models(directory: Path, force: bool = False) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for spec in MODEL_SPECS.values():
        target = directory / spec.filename
        if target.exists() and not force:
            if _digest(target) == spec.sha256:
                continue
            raise RuntimeError(f"existing {spec.filename} has a checksum mismatch; use --force")
        request = Request(spec.url, headers={"User-Agent": "attendance-system-model-fetcher/0.1"})
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=f"{spec.filename}.", suffix=".part", delete=False
        ) as stream:
            temporary = Path(stream.name)
            try:
                with urlopen(request, timeout=120) as response:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
                if _digest(temporary) != spec.sha256:
                    raise RuntimeError(f"checksum mismatch for downloaded {spec.filename}")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
    errors = verify_models(directory)
    if errors:
        raise RuntimeError("; ".join(errors))
