# Cloud platform architecture

AtlasPay and Nexus use a deliberately separated deployment topology:

    Browser
      -> Nexus (Vercel)
           -> authenticated HTTPS
              AtlasPay API (Railway)
                 -> TLS PostgreSQL
                    Neon production branch
              Java authorization service (Railway, private)
              reconciliation runner (Railway scheduled service)

## Responsibilities

- Vercel hosts the Next.js/TypeScript Nexus console and its preview deployments.
- Railway hosts long-running API and JVM services, health checks, deployment logs and scheduled jobs.
- Neon is the durable PostgreSQL provider. Production data is kept on a protected production branch; preview environments use isolated branches.
- GitHub Actions remains the quality gate for tests, type checks, container builds and security checks.

## Service boundaries

### AtlasPay API

The root Dockerfile deploys the FastAPI service. It exposes:

- GET /health for liveness;
- GET /v1/ops/snapshot for authenticated operational state;
- payment lifecycle endpoints.

Required Railway variables:

- DATABASE_URL — Neon PostgreSQL connection string;
- ATLASPAY_OPS_TOKEN — secret used by the operational API;
- ATLASPAY_DEMO_BOOTSTRAP=1 only for the public deterministic demo environment.

### Java authorization service

The java-service directory is deployed as a separate Railway service from its own Dockerfile. It should not receive a public domain for the demo. Its internal contract is protected by service-level authentication before it is used outside the local demonstration.

Use a JDBC-formatted SPRING_DATASOURCE_URL. Do not pass a raw postgresql:// URL to Spring Boot.

Required production variables:

- SPRING_PROFILES_ACTIVE=production;
- SPRING_DATASOURCE_URL=jdbc:postgresql://...;
- SPRING_DATASOURCE_USERNAME;
- SPRING_DATASOURCE_PASSWORD;
- ATLASPAY_INTERNAL_TOKEN.

Railway supplies PORT; the application maps it to its HTTP server port.

### Reconciliation

Reconciliation is a restartable batch capability, not an HTTP request that silently mutates state. The deployment should use a scheduled Railway job or a protected internal trigger. Every run must expose an execution ID, status, processed count and mismatch count.

## Migration policy

Schema changes must be applied by a controlled migration step before application traffic is enabled:

1. connect to the target Neon branch;
2. acquire the migration advisory lock;
3. verify checksums of applied migrations;
4. apply pending migrations transactionally;
5. run smoke checks;
6. deploy API and JVM services.

The web services should not independently race to create or mutate production schema during startup.

## Verification gates

A deployment is considered verified only when all of these pass:

- Vercel Nexus loads without authentication for the recruiter-facing demo;
- Nexus reports atlaspay-live, never fixture-demo;
- AtlasPay health and protected snapshot endpoints respond over HTTPS;
- a database restart or application redeploy preserves payment and operational state;
- repeated requests with the same idempotency key return the original result;
- a changed request with the same key returns a conflict;
- Java authorization writes its decision and outbox event atomically;
- reconciliation can restart without duplicating results;
- CI, dependency audit and container security checks are green.

AtlasPay remains a payment-system simulation. This architecture demonstrates engineering controls and failure behavior; it does not claim live card-network connectivity or real-money processing.
