# Security and privacy

Face embeddings are sensitive biometric data. A normalized vector is not anonymous. Store the database, signing key, and API keys under the same access controls used for other sensitive data. Limit database access and set a retention policy before enrolling anyone.

## In the service

- Administrator and terminal API keys come from environment configuration and use constant-time comparison.
- Scope checks happen before protected behavior. Terminal credentials cannot enroll, delete, correct, or read history.
- Confirmation tokens are HMAC-SHA256 signed, carry only an opaque identity UUID and timing claims, and expire after a short configured interval. The token identity cannot be replaced in the attendance request.
- Attendance writes require a client idempotency key. A key is bound to a hash of its request and cannot silently change meaning.
- Uploads require JPEG or PNG content type, matching file signatures, a decoded image, bounded bytes, bounded pixels, bounded dimensions, and exactly one detected face.
- Images are processed in memory and discarded after inference. Failed recognition attempts are not persisted.
- Logs contain event names, safe error codes, request IDs, status, and duration. They do not contain image data, embeddings, API keys, tokens, display names, or identity UUIDs.
- Identity deletion removes the profile and embedding and anonymizes identity links in attendance history. Corrections are append-only.

## Required external controls

Terminate HTTPS at an authenticated gateway. Apply per-key and per-client throttling before requests reach the API. Provide a liveness and anti-spoofing control suitable for the deployment. This version does not implement those controls, and a static image match must not be treated as proof of physical presence.

Before a real deployment, obtain legal and privacy review, define notice and consent, limit access, document retention and deletion, calibrate with representative local data, measure error trade-offs, test capacity, and define incident handling. This repository does not certify employment, biometric, accessibility, or regulatory compliance.

## Secrets and operations

Never commit `.env`, API keys, signing keys, calibration data, face images, embeddings, or model files. Rotate keys using an external secret manager. Use a separate signing key when invalidating all outstanding confirmations. Back up encrypted database data only under an approved retention policy.
