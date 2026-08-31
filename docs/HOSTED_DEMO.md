# Hosted demo runtime

AtlasPay can run as a durable public demo behind any container host that provides PostgreSQL and HTTPS.

## Required environment

- `DATABASE_URL` — PostgreSQL connection string.
- `ATLASPAY_OPS_TOKEN` — bearer token required by `/v1/ops/snapshot`.
- `ATLASPAY_DEMO_BOOTSTRAP=1` — run migrations and seed deterministic network scenarios before the API starts.
- `PORT` — optional platform-provided HTTP port; defaults to `8000`.

Keep `ATLASPAY_OPS_TOKEN` server-side. Nexus reads the same token from its own server environment and does not expose it to the browser.

## Startup behavior

When `ATLASPAY_DEMO_BOOTSTRAP=1`, the container:

1. applies pending migrations with the repository migration runner;
2. verifies recorded migration checksums;
3. acquires a PostgreSQL advisory lock for demo seeding;
4. seeds accepted, timeout/late-response and known-local transport-failure observations only when the observation table is empty;
5. starts Uvicorn on the platform port.

The seed lock makes concurrent starts safe from duplicate demo initialization. Existing durable demo data is preserved across normal restarts.

## Health and operator endpoints

- `GET /health` — unauthenticated liveness endpoint.
- `GET /docs` — FastAPI OpenAPI UI.
- `GET /v1/ops/snapshot` — protected operational state; requires `Authorization: Bearer <ATLASPAY_OPS_TOKEN>`.

## Scope

This deployment mode remains a payment-system simulation. It does not connect to a live card network, process real money, or imply production traffic scale.
