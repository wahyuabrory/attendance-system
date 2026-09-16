# Architecture

The service has four runtime boundaries.

1. FastAPI validates headers, multipart fields, JSON bodies, response shapes, and request IDs.
2. The inference boundary decodes an upload, detects one face with YuNet, aligns it, and creates an SFace embedding. Enrollment normalizes every sample, averages the samples, normalizes the result again, and stores one 128-value vector.
3. PostgreSQL with pgvector stores identity profiles, one embedding per identity, attendance events, append-only corrections, and idempotency records. Matching orders all enrolled vectors by exact cosine distance. No approximate index is used.
4. A terminal receives a short-lived HMAC confirmation token after a match. Only a later explicit confirmation writes `check_in` or `check_out`.

The API process creates an engine and session factory at startup. It does not apply migrations. Migrations are an operator or Compose migration-service action.

Failed recognition attempts and raw image bytes never enter persistence. The deletion transaction removes the biometric row and clears identity attribution from historical events. Correction rows preserve the original event while history computes the latest effective type.

CPU inference is the only supported runtime path. A semaphore bounds model work in one API process. A gateway, not this application, must handle HTTPS, request throttling, and liveness or anti-spoofing checks.
