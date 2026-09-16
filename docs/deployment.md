# Deployment notes

This project provides a local Docker shape, not a complete production platform.

## Local Compose

`docker compose up --build` builds the source-only image, downloads the fixed model objects during the build, starts PostgreSQL with pgvector, runs `alembic upgrade head` in a one-shot migration service, then starts the API. The final API image runs as the non-root `app` user.

For a fresh local setup:

```sh
cp .env.example .env
# Set API keys and the signing key in .env.
docker compose up --build
```

Do not use the Compose database password or direct HTTP setup for a public deployment.

## Production checklist

- Run `uv run alembic upgrade head` as a separate release or migration action. Never make the API startup command migrate.
- Set `ATTENDANCE_ENVIRONMENT=production`, all three secrets, a verified model directory, and `ATTENDANCE_CALIBRATION_PATH`.
- Put an HTTPS gateway in front of the service. The gateway owns certificates, client throttling, and liveness or anti-spoofing controls.
- Restrict database and model-file permissions. Back up the database according to the approved retention policy.
- Keep model files outside Git and verify them before each image build or release.
- Observe only safe structured logs. Add an external log sink, alerts, and capacity controls without recording biometric payloads.
- Validate the threshold for the target camera and population. The development demonstration threshold is not deployment evidence.

The first version is CPU-only and uses exact database vector scans. It makes no throughput, accuracy, or unattended-use claim.
