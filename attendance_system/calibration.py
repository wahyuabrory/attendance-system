from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import RuntimeConfigError


class CalibrationArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int = Field(strict=True, ge=1, le=1)
    threshold: float = Field(strict=True, ge=0, le=1)
    ambiguity_margin: float = Field(strict=True, ge=0, le=1)
    created_at: str


@dataclass(frozen=True, slots=True)
class ScoreRecord:
    score: float
    same_identity: bool
    second_score: float | None = None


def load_calibration(path: Path | None, production: bool) -> CalibrationArtifact:
    if path is None:
        if production:
            raise RuntimeConfigError("calibration artifact is required in production")
        return CalibrationArtifact(
            schema_version=1,
            threshold=0.363,
            ambiguity_margin=0.05,
            created_at="development-demonstration",
        )
    try:
        artifact = CalibrationArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        raise RuntimeConfigError("calibration artifact is missing or invalid") from None
    return artifact


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.lower() in {"1", "true", "same", "genuine", "match"}:
        return True
    if isinstance(value, str) and value.lower() in {
        "0",
        "false",
        "different",
        "impostor",
        "nonmatch",
    }:
        return False
    raise ValueError("label must identify a same-identity or different-identity pair")


def load_scores(path: Path) -> list[ScoreRecord]:
    try:
        if path.suffix.lower() == ".csv":
            with path.open(newline="", encoding="utf-8") as source:
                rows: list[dict[str, Any]] = list(csv.DictReader(source))
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw if isinstance(raw, list) else [raw]
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("each score row must be an object")
            score = float(row["score"])
            second = row.get("second_score")
            result.append(
                ScoreRecord(
                    score, _as_bool(row["same_identity"]), None if second is None else float(second)
                )
            )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValueError("scores must be JSON or CSV rows with score and same_identity") from None
    if not result:
        raise ValueError("scores file is empty")
    if any(
        not math.isfinite(score) or score < -1 or score > 1
        for item in result
        for score in (item.score, item.second_score)
        if score is not None
    ):
        raise ValueError("scores must be finite values between -1 and 1")
    return result


def calibrate_scores(
    records: list[ScoreRecord], target_far: float, margin: float
) -> CalibrationArtifact:
    if not 0 <= target_far <= 1:
        raise ValueError("target FAR must be between 0 and 1")
    if not 0 <= margin <= 1:
        raise ValueError("ambiguity margin must be between 0 and 1")
    impostor = [item.score for item in records if not item.same_identity]
    genuine = [item.score for item in records if item.same_identity]
    if not impostor or not genuine:
        raise ValueError("scores must contain both same-identity and different-identity rows")
    candidates = sorted(set(impostor + genuine), reverse=True)
    valid = [
        candidate
        for candidate in candidates
        if sum(score >= candidate for score in impostor) / len(impostor) <= target_far
    ]
    if valid:
        threshold = min(valid)
    else:
        threshold = math.nextafter(max(impostor), math.inf)
    if threshold > 1:
        raise ValueError("target FAR cannot be reached with the supplied scores")
    return CalibrationArtifact(
        schema_version=1,
        threshold=max(0.0, min(1.0, threshold)),
        ambiguity_margin=margin,
        created_at=datetime.now(UTC).isoformat(),
    )


def evaluate_scores(records: list[ScoreRecord], threshold: float, margin: float) -> dict[str, Any]:
    if not 0 <= threshold <= 1 or not 0 <= margin <= 1:
        raise ValueError("threshold and ambiguity margin must be between 0 and 1")
    counts = {"matched": 0, "unknown": 0, "ambiguous": 0}
    false_accepts = false_rejects = 0
    for item in records:
        if (
            item.second_score is not None
            and item.score >= threshold
            and item.score - item.second_score < margin
        ):
            decision = "ambiguous"
        elif item.score >= threshold:
            decision = "matched"
        else:
            decision = "unknown"
        counts[decision] += 1
        if item.same_identity and decision != "matched":
            false_rejects += 1
        if not item.same_identity and decision == "matched":
            false_accepts += 1
    same_identity_rows = sum(item.same_identity for item in records)
    different_identity_rows = len(records) - same_identity_rows
    return {
        "rows": len(records),
        "decisions": counts,
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "false_accept_rate": false_accepts / different_identity_rows
        if different_identity_rows
        else 0.0,
        "false_reject_rate": false_rejects / same_identity_rows if same_identity_rows else 0.0,
        "threshold": threshold,
        "ambiguity_margin": margin,
    }
