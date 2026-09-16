# Agent instructions

## Purpose

Maintain this repository as a source-only reference implementation of attendance confirmation with face recognition. Keep its claims limited to behavior that code and tests prove.

## Sources of truth

- For endpoint or command behavior, read `docs/api.md` and the corresponding implementation in `attendance_system/`.
- For trust boundaries, biometric-data handling, or authentication changes, read `docs/security.md`.
- For runtime or container changes, read `docs/deployment.md`, `Dockerfile`, and `compose.yaml`.
- For model files and checksums, use `MODEL_SPECS` in `attendance_system/model_download.py`. Update `docs/model-licenses.md` when a model source or license changes.
- For database structure, read the ordered migrations in `alembic/` and the models in `attendance_system/models.py`.
- For validation, follow `.github/workflows/validation.yml`.

## Invariants

- Keep real face images, identity datasets, biometric embeddings, calibration inputs, model binaries, secrets, and notebook files outside Git.
- Process uploads in memory. Persist one aggregate normalized embedding for each enrolled identity.
- Require exactly one detected face for each enrollment or recognition image.
- Keep recognition separate from attendance creation. Only a valid short-lived confirmation token can authorize an explicit check-in or check-out event.
- Return `unknown` or `ambiguous` without creating an attendance record.
- Preserve administrator and terminal API-key scopes.
- Keep corrections append-only. Identity deletion removes the profile and embedding and anonymizes historical attendance links.
- Require a calibration artifact in production mode. Treat the development threshold only as a local demonstration value.

## Change workflow

1. Read the source of truth for the behavior being changed.
2. Make the smallest complete change and preserve unrelated behavior.
3. Use `uv` and update both `pyproject.toml` and `uv.lock` for dependency changes.
4. Add an Alembic migration for every database schema change. Keep existing migrations immutable.
5. Test observable behavior through the public API or CLI. Use synthetic embeddings and fake model adapters, with no face-image fixtures.
6. Update the one canonical document that owns the changed behavior. Link to it from other documents instead of copying its details.
7. Run the validation defined in `.github/workflows/validation.yml`. Report any check that local infrastructure cannot run.

## Code rules

- Keep Python fully typed and compatible with strict mypy checks.
- Validate data at HTTP, configuration, file, and token trust boundaries.
- Return structured errors that state what failed without exposing secrets or biometric data.
- Keep logs free of image bytes, embeddings, credentials, tokens, display names, and identity identifiers.
- Prefer direct code with explicit state ownership over new abstraction layers.
