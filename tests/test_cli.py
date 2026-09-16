from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from attendance_system.cli import main


def test_verify_models_reports_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["attendance-system", "verify-models", "--directory", str(tmp_path)]
    )
    assert main() == 1
    assert "missing face_detection_yunet_2023mar.onnx" in capsys.readouterr().out


def test_calibrate_and_evaluate_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scores = tmp_path / "scores.json"
    artifact = tmp_path / "calibration.json"
    scores.write_text(
        json.dumps(
            [
                {"score": 0.9, "same_identity": True},
                {"score": 0.8, "same_identity": True},
                {"score": 0.2, "same_identity": False},
                {"score": 0.1, "same_identity": False},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "attendance-system",
            "calibrate",
            "--scores",
            str(scores),
            "--output",
            str(artifact),
            "--target-far",
            "0",
        ],
    )
    assert main() == 0
    threshold = json.loads(artifact.read_text(encoding="utf-8"))["threshold"]
    assert 0.2 < threshold <= 0.8

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "attendance-system",
            "evaluate",
            "--scores",
            str(scores),
            "--threshold",
            str(threshold),
        ],
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["rows"] == 4
