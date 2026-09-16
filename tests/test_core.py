from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from pydantic import SecretStr

from attendance_system.calibration import ScoreRecord, evaluate_scores
from attendance_system.config import Settings
from attendance_system.errors import AppError, RuntimeConfigError
from attendance_system.inference import aggregate_embeddings, normalize_embedding
from attendance_system.security import TokenSigner, authenticate


def test_embedding_normalization_and_aggregation() -> None:
    assert normalize_embedding([3.0, 4.0]) == pytest.approx([0.6, 0.8])
    aggregate = aggregate_embeddings([[1.0, 0.0], [0.0, 1.0]])
    assert aggregate == pytest.approx([2**-0.5, 2**-0.5])


def test_invalid_embedding_is_rejected() -> None:
    with pytest.raises(AppError, match="invalid embedding"):
        normalize_embedding(np.array([np.nan, 1.0]))


def test_match_decisions_cover_unknown_ambiguous_and_matched() -> None:
    result = evaluate_scores(
        [
            ScoreRecord(score=0.40, same_identity=True),
            ScoreRecord(score=0.35, second_score=0.34, same_identity=True),
            ScoreRecord(score=0.10, same_identity=False),
        ],
        threshold=0.30,
        margin=0.05,
    )
    assert result["decisions"] == {"matched": 1, "unknown": 1, "ambiguous": 1}


def test_confirmation_token_expires_and_rejects_tampering() -> None:
    signer = TokenSigner("s" * 32, ttl_seconds=60)
    issued = datetime(2026, 1, 1, tzinfo=UTC)
    identity_id = uuid4()
    token, _ = signer.issue(identity_id, now=issued)

    assert signer.verify(token, now=issued + timedelta(seconds=30)).identity_id == identity_id

    with pytest.raises(AppError):
        signer.verify(token + "x", now=issued + timedelta(seconds=30))
    with pytest.raises(AppError):
        signer.verify(token, now=issued + timedelta(seconds=60))


def test_api_key_authentication_is_scope_specific() -> None:
    principal = authenticate("a" * 32, "a" * 32, "admin")
    assert principal.scope == "admin"
    with pytest.raises(AppError):
        authenticate("t" * 32, "a" * 32, "admin")


def test_api_configuration_requires_distinct_secrets() -> None:
    with pytest.raises(RuntimeConfigError, match="must differ"):
        Settings(
            database_url="postgresql+asyncpg://attendance:attendance@localhost/attendance",
            admin_api_key=SecretStr("a" * 32),
            terminal_api_key=SecretStr("a" * 32),
            token_signing_key=SecretStr("s" * 32),
        ).validate_for_api()

    with pytest.raises(RuntimeConfigError, match="must differ"):
        Settings(
            database_url="postgresql+asyncpg://attendance:attendance@localhost/attendance",
            admin_api_key=SecretStr("a" * 32),
            terminal_api_key=SecretStr("t" * 32),
            token_signing_key=SecretStr("a" * 32),
        ).validate_for_api()


def test_production_rejects_example_secrets() -> None:
    with pytest.raises(RuntimeConfigError, match="must be replaced"):
        Settings(
            environment="production",
            database_url="postgresql+asyncpg://attendance:attendance@localhost/attendance",
            admin_api_key=SecretStr("replace-with-a-random-administrator-key"),
            terminal_api_key=SecretStr("t" * 32),
            token_signing_key=SecretStr("s" * 32),
            calibration_path=Path("calibration.json"),
        ).validate_for_api()
