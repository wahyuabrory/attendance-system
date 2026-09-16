# Attendance System

Attendance System is an API for recording check-ins and check-outs with face recognition. An administrator first enrolls each person with several photos. At the attendance terminal, a new photo is compared with the enrolled faces. A clear match creates a short-lived confirmation that the terminal can use to record a check-in or check-out.

Face recognition only suggests an identity. It never records attendance by itself. The terminal must confirm the match and choose the event type, which keeps attendance recording separate from the model's decision.

## How it works

1. An administrator enrolls an identity with several images of the same person.
2. YuNet finds exactly one face and its landmarks in each image.
3. SFace turns each aligned face into a numeric embedding. The service normalizes and averages those embeddings, then stores one aggregate embedding.
4. A terminal sends a new image. The service compares its embedding with enrolled embeddings and returns `matched`, `unknown`, or `ambiguous`.
5. A match returns a short-lived signed token. The terminal submits that token with an explicit `check_in` or `check_out` event and an idempotency key.

Raw images are processed in memory and discarded. Unknown and ambiguous results create no attendance record.

## Face detection and matching

The pipeline separates face detection from face recognition. YuNet answers "where is the face?" SFace answers "which enrolled embedding is most similar?" This split keeps the system understandable and lets identities be enrolled without retraining a fixed classifier.

### YuNet

YuNet is a compact, anchor-free face detector. It returns a face box and landmarks that SFace uses for alignment. Its small design suits CPU inference, and it fits directly into OpenCV's face-detection API.

Paper: Wei Wu, Hanyang Peng, and Shiqi Yu, ["YuNet: A Tiny Millisecond-level Face Detector"](https://doi.org/10.1007/s11633-023-1423-y), *Machine Intelligence Research*, 2023.

### SFace

SFace converts an aligned face into a 128-value embedding. The service stores that embedding and uses cosine similarity for matching. The OpenCV model runs on CPU and works with YuNet through the same alignment and recognition APIs.

The SFace paper introduces a sigmoid-constrained hypersphere loss. Its goal is to reduce overfitting to noisy training samples while learning useful distances between identities.

Paper: Yaoyao Zhong, Weihong Deng, Jiani Hu, Dongyue Zhao, Xian Li, and Dongchao Wen, ["SFace: Sigmoid-Constrained Hypersphere Loss for Robust Face Recognition"](https://doi.org/10.1109/TIP.2020.3048632), *IEEE Transactions on Image Processing*, 2021.

These papers explain the model designs. They do not prove that this repository is accurate enough for a workplace. Each real deployment needs its own calibration and evaluation data.

## Tech stack

| Technology | Role in this project |
| --- | --- |
| Python | Runs the API, inference pipeline, command-line tools, and migrations. |
| FastAPI and Pydantic | Validate HTTP input, configuration, and response shapes. They also generate the OpenAPI contract. |
| OpenCV | Loads the YuNet and SFace ONNX models, aligns faces, and runs CPU inference. |
| NumPy and Pillow | Normalize embeddings and safely decode JPEG or PNG uploads. |
| PostgreSQL and pgvector | Store identities, embeddings, attendance records, corrections, and idempotency records. pgvector performs cosine-distance matching. |
| SQLAlchemy and asyncpg | Provide typed database models and asynchronous PostgreSQL access. |
| Alembic | Applies explicit, ordered database migrations outside API startup. |
| `uv` | Installs the locked Python environment and runs project commands. |
| Docker Compose | Starts PostgreSQL, runs migrations, and starts the API for local use. |
| GitHub Actions | Checks formatting, lint, types, tests, migrations, and the container build. |

## Run with Docker Compose

Install Docker with Compose support, then run:

```sh
cp .env.example .env
# Replace the three placeholder keys in .env with random values.
docker compose up --build
```

The API listens on `http://127.0.0.1:8000`. OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

Check the process and its dependencies with:

```sh
curl http://127.0.0.1:8000/healthz
curl http://127.0.0.1:8000/readyz
```

## Local development

Use `uv` for the Python environment and lockfile.

```sh
cp .env.example .env
uv sync --locked
uv run attendance-system download-models
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn attendance_system.main:app --reload
```

Run the local checks with:

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy attendance_system tests
uv run pytest
```

PostgreSQL integration tests use `ATTENDANCE_TEST_DATABASE_URL`. They skip when it is not set. GitHub Actions supplies a PostgreSQL service with pgvector for the full test run.

## Models and calibration

Model binaries are not stored in Git. The download command fetches fixed files from OpenCV Zoo and checks their SHA-256 digests.

```sh
uv run attendance-system download-models
uv run attendance-system verify-models
```

Development mode can use the demonstration threshold in `load_calibration` from `attendance_system/calibration.py`. Production mode requires a calibration artifact built from data for the target population and camera setup. [API and CLI contracts](docs/api.md) define the score format and commands.

## Safety boundary

This repository is a reference implementation, not a complete biometric attendance product. Static-image matching does not prove physical presence. A real deployment needs legal and privacy review, informed consent, a retention policy, HTTPS, request throttling, liveness checks, monitoring, and capacity testing.

Read [Security and privacy](docs/security.md) before using the system with real people.

## Third-party notices

The project source uses the Apache-2.0 license. Third-party packages and model files keep their own licenses.

Python dependencies come from PyPI according to `uv.lock`. This includes FastAPI, Pydantic, SQLAlchemy, Alembic, asyncpg, pgvector, NumPy, Pillow, OpenCV Python, Uvicorn, and their transitive dependencies. The lockfile records the installed packages and source metadata. Each package keeps its own license and notices.

The model downloader fetches these OpenCV Zoo files during setup or image build. Git ignores the downloaded files.

| Model file | OpenCV Zoo revision | SHA-256 | Upstream license |
| --- | --- | --- | --- |
| `face_detection_yunet_2023mar.onnx` | `47534e27c9851bb1128ccc0102f1145e27f23f98` | `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4` | MIT |
| `face_recognition_sface_2021dec.onnx` | `47534e27c9851bb1128ccc0102f1145e27f23f98` | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | Apache-2.0 |

The exact download URLs live in `MODEL_SPECS` in `attendance_system/model_download.py`. [Model licenses](docs/model-licenses.md) links to the upstream OpenCV Zoo directories and license files. Review those terms before redistributing the model files.

## Documentation

- [API and CLI contracts](docs/api.md) define endpoints, request formats, responses, and commands.
- [Architecture](docs/architecture.md) explains the runtime components and data flow.
- [Security and privacy](docs/security.md) defines trust boundaries and required external controls.
- [Deployment notes](docs/deployment.md) covers runtime responsibilities and production limits.
- [Model licenses](docs/model-licenses.md) records upstream model sources and terms.

## Repository layout

```text
attendance_system/   Application package
alembic/             Ordered database migrations
tests/               Unit, CLI, and PostgreSQL API tests
docs/                Product and operational documentation
```
