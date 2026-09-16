from __future__ import annotations

import argparse
import json
from pathlib import Path

from .calibration import calibrate_scores, evaluate_scores, load_scores
from .model_download import download_models, verify_models


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="attendance-system")
    subparsers = command.add_subparsers(dest="command", required=True)

    for name in ("download-models", "verify-models"):
        item = subparsers.add_parser(name, help=f"{name.replace('-', ' ')}")
        item.add_argument("--directory", type=Path, default=Path("models"))
    subparsers.choices["download-models"].add_argument("--force", action="store_true")

    calibrate = subparsers.add_parser(
        "calibrate", help="create a calibration artifact from local score rows"
    )
    calibrate.add_argument("--scores", type=Path, required=True)
    calibrate.add_argument("--output", type=Path, required=True)
    calibrate.add_argument("--target-far", type=float, default=0.001)
    calibrate.add_argument("--ambiguity-margin", type=float, default=0.05)

    evaluate = subparsers.add_parser("evaluate", help="summarize decisions from local score rows")
    evaluate.add_argument("--scores", type=Path, required=True)
    evaluate.add_argument("--threshold", type=float, required=True)
    evaluate.add_argument("--ambiguity-margin", type=float, default=0.05)
    return command


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "download-models":
            download_models(args.directory, args.force)
            print(json.dumps({"status": "downloaded", "directory": str(args.directory)}))
        elif args.command == "verify-models":
            errors = verify_models(args.directory)
            if errors:
                for error in errors:
                    print(error)
                return 1
            print(json.dumps({"status": "verified", "directory": str(args.directory)}))
        elif args.command == "calibrate":
            artifact = calibrate_scores(
                load_scores(args.scores), args.target_far, args.ambiguity_margin
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
            print(artifact.model_dump_json())
        elif args.command == "evaluate":
            print(
                json.dumps(
                    evaluate_scores(load_scores(args.scores), args.threshold, args.ambiguity_margin)
                )
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
