# ADR 0005: Versioned read-only operator snapshot contract

## Status

Accepted for the AtlasPay/Nexus integration boundary.

## Context

Nexus needs an operational view of AtlasPay without reaching directly into AtlasPay's database, mutating payment state, or presenting fixture values as live telemetry. AtlasPay currently has durable PostgreSQL state for payments, ledger/reconciliation, and the transactional outbox. Network observability exists as process-local Prometheus/OpenTelemetry instrumentation and therefore cannot yet provide a durable cross-process snapshot.

A control-plane contract must distinguish a measured zero from a metric that is not available. It must also avoid exposing internal operational counts to unauthenticated callers.

## Decision

AtlasPay publishes `GET /v1/ops/snapshot` as a versioned, read-only contract.

The v1 contract:

- derives payment counts, payment-operation counts, outbox backlog, poison-message counts, and oldest unpublished-event age from PostgreSQL;
- runs the existing read-only reconciliation inspector and exposes discrepancy counts/kinds, never a repair action;
- represents each major section as `available` or `unavailable` and uses nullable values for unavailable measurements instead of substituting zero;
- reports `data_state=partial` while any contract section is unavailable;
- reports the network section as unavailable until network telemetry has a durable snapshot source;
- classifies reconciliation discrepancies or poison outbox events as `critical`, ordinary unpublished outbox backlog as `degraded`, and otherwise measured durable state as `healthy`;
- requires `Authorization: Bearer <token>` matching `ATLASPAY_OPS_TOKEN` using constant-time comparison;
- fails closed with HTTP 503 when no operations token is configured and HTTP 401 for missing/invalid credentials.

The endpoint is observational only. It does not capture/refund/reverse payments, repair ledger data, publish/replay outbox events, or perform network retries.

## Consequences

Nexus can consume a stable API instead of sharing AtlasPay persistence concerns. Consumers must handle partial/unavailable sections explicitly and must not derive authorization rate, issuer latency, or transaction-network views from absent network data.

The bearer token is an application-level portfolio boundary, not a complete production identity architecture. A real deployment would additionally terminate TLS, manage secret rotation, apply network policy/rate limits, and likely use workload identity or a dedicated service-to-service authentication mechanism.

Adding durable network telemetry later can evolve the network section without changing the meaning of existing zero/unknown states. A breaking schema change requires a new contract version.

## Verification

CI exercises:

- schema/health classification and unavailable-field semantics;
- fail-closed authentication behavior;
- the real PostgreSQL aggregation query against PostgreSQL 16;
- the existing reconciliation path rather than a separate dashboard-only accounting implementation.
