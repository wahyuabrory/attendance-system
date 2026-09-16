# API and CLI contracts

## HTTP

The service accepts JSON for attendance and correction requests. Multipart endpoints reject unsupported content types, malformed bytes, oversized files, excessive dimensions, and invalid face counts. The API does not accept URLs or base64 image fields.

Use these headers on protected routes:

```text
X-API-Key: <administrator-or-terminal-key>
X-Request-ID: optional-safe-correlation-value
```

### Enrollment

```sh
curl -X POST http://127.0.0.1:8000/v1/identities \
  -H 'X-API-Key: admin-key' \
  -F 'display_name=Example' \
  -F 'images=@one.jpg;type=image/jpeg' \
  -F 'images=@two.jpg;type=image/jpeg' \
  -F 'images=@three.jpg;type=image/jpeg'
```

Response `201`:

```json
{
  "identity_id": "opaque-uuid",
  "display_name": "Example",
  "image_count": 3,
  "created_at": "2025-01-01T00:00:00Z"
}
```

Images are decoded and processed in memory. The database stores only the aggregate embedding.

### Recognition and confirmation

```sh
curl -X POST http://127.0.0.1:8000/v1/recognitions \
  -H 'X-API-Key: terminal-key' \
  -F 'image=@query.jpg;type=image/jpeg'
```

A `matched` response contains the identity UUID and a signed token. `unknown` and `ambiguous` responses contain neither. Recognition alone creates no attendance event.

```sh
curl -X POST http://127.0.0.1:8000/v1/attendance \
  -H 'X-API-Key: terminal-key' \
  -H 'Idempotency-Key: terminal-device-unique-value' \
  -H 'Content-Type: application/json' \
  -d '{"confirmation_token":"<token>","event_type":"check_in"}'
```

The event type must be `check_in` or `check_out`. The token identity is authoritative. The request cannot supply or replace an identity UUID. A first write returns `201`; an identical retry returns `200`; reusing a key with a different request returns `409`.

### History and corrections

`GET /v1/attendance` is administrator-only. It supports `identity_id`, `event_type`, `from`, `to`, `limit=1..100`, and `offset=0..10000`. Results are ordered by occurrence time and event UUID. The response has `has_more` and does not perform an unbounded read.

`POST /v1/attendance/{event_id}/corrections` is administrator-only:

```json
{"event_type":"check_out","reason":"Recorded direction was wrong"}
```

The original row is unchanged. History reports the latest correction as the effective event type and also returns the original type. Correction rows retain only a SHA-256 fingerprint of the administrator key, not the key itself.

`DELETE /v1/identities/{identity_id}` removes the profile and embedding in one transaction. It clears the identity UUID and display name from past events. Anonymous event facts and correction rows remain.

## CLI

The command is `attendance-system`.

- `download-models [--directory DIR] [--force]` downloads the two fixed OpenCV Zoo model objects and verifies each SHA-256 digest before an atomic rename.
- `verify-models [--directory DIR]` exits `0` only when both expected files exist and match the fixed digests.
- `calibrate --scores FILE --output FILE [--target-far FLOAT] [--ambiguity-margin FLOAT]` reads JSON or CSV rows with `score` and `same_identity`, requires both classes, and writes a versioned JSON artifact.
- `evaluate --scores FILE --threshold FLOAT [--ambiguity-margin FLOAT]` reads the same rows. An optional `second_score` field lets it report ambiguous decisions. It prints decision counts and error counts for the supplied local file.
- `uv run alembic upgrade head` applies the schema migration. It is separate from API startup.

JSON score example:

```json
[
  {"score": 0.81, "same_identity": true},
  {"score": 0.22, "same_identity": false, "second_score": 0.18}
]
```

The command does not download data, include data in the repository, or use any project-specific accuracy result.
