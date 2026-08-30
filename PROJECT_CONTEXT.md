# AtlasPay Project Context

## Portfolio role

AtlasPay is the flagship payments, distributed-systems, and payments-analytics project in the `soufianeelbiki1` portfolio. It should demonstrate correctness under retries, explicit failure semantics, protocol interoperability, durable state, ledgering, event delivery, observability, analytics/decision support, and production-minded trade-offs without claiming fake scale or impossible exactly-once guarantees across external boundaries.

## Current state

As of 2026-08-30, the repository already contains:

- FastAPI payment-intent API and explicit payment lifecycle.
- Durable PostgreSQL idempotency with request fingerprinting and a unique database key.
- Decimal-safe money modeling using integer minor units.
- Strict ISO 8583 codec support with primary/secondary bitmaps, fixed/LLVAR/LLLVAR validation, and binary DE55 handling.
- Protocol-independent canonical authorization models.
- ISO 8583 mapping plus MTI/STAN/RRN correlation groundwork.
- Schema-neutral ISO 20022 card-authorization projection through the canonical model with explicit STAN/DE55 loss reporting and fail-closed RRN bridge constraints; no XML/XSD conformance claim.
- Versioned SQL migrations with checksum drift detection and a PostgreSQL advisory migration lock.
- Append-only PostgreSQL double-entry ledger with balanced/currency invariants.
- Atomic PostgreSQL capture/refund/reversal operations that update payment state and post a ledger journal in the same transaction.
- Replay-safe operation idempotency using request fingerprints, a durable unique key, and a PostgreSQL advisory transaction lock.
- Transactional outbox events committed with payment state, ledger journal, and operation record.
- Database-backed at-least-once publisher reference using `FOR UPDATE SKIP LOCKED`, bounded retry accounting, and poison-message retention.
- Idempotent consumer claims keyed by `(consumer_name, event_id)`.
- Deterministic read-only reconciliation across payments, operations, journals, ledger entries, and outbox event linkage.
- Explicit replay controls that can reset only unpublished outbox events; published delivery history is never silently rewritten.
- Transport-independent network coordination with explicit accepted, mismatch, timeout, late-response, and duplicate outcomes.
- Canonical-model issuer/acquirer routing with longest-prefix selection, currency eligibility, and explicit ambiguity rejection.
- One-to-one original/reversal network correlation linkage with explicit reasons and no external-delivery claim.
- Strict EMV BER-TLV decoding for DE55 with constructed-template recursion, duplicate preservation, bounded nesting/length parsing, known-tag metadata, and explainable five-byte TVR decoding.
- Explicit byte-oriented network transport port plus ISO 8583 adapter boundary; transport timeouts preserve ambiguous external-delivery status, while malformed responses fail at the adapter boundary.
- Authorization network flow ties canonical/wire correlation equality, issuer routing, coordinator deadlines, transport outcomes, timeout-triggered reversal correlation, late original responses, and safe cancellation after known-local transport failure without claiming reversal delivery.
- Low-cardinality Prometheus network attempt/outcome/latency/reversal metrics and exporter-neutral OpenTelemetry spans that deliberately exclude PAN, STAN, RRN, DE55, and transaction identifiers from labels.
- Deterministic transport-boundary fault injection for known-local failures, delivery-ambiguous timeouts, and malformed ISO 8583 responses.
- A versioned read-only operator snapshot contract for Nexus that measures durable payments, operations, reconciliation, and outbox state from PostgreSQL, represents unavailable sections as nullable/unavailable rather than fake zeroes, and keeps non-durable network metrics explicitly unavailable.
- The operator snapshot is fail-closed behind `ATLASPAY_OPS_TOKEN`; an unset token disables the endpoint and invalid bearer credentials are rejected.
- Nexus now consumes the protected AtlasPay API when live configuration is present, fails closed on source/config/contract failure without fixture fallback, and renders only producer fields that are actually available.
- A payments analytics warehouse under `analytics/` with PostgreSQL SQL marts for daily payment creation/current-status composition, capture/refund/reversal lifecycle timing, outbox reliability, and daily ledger debit-credit controls.
- Analytics mart contracts explicitly retain currency for monetary grains, distinguish current payment state from historical funnel events, distinguish lifecycle timing from network latency, and use the same retry-limit semantics as operational reporting.
- PostgreSQL CI contract tests execute the analytics marts against the migrated schema and verify their output columns.
- PostgreSQL integration tests exercise the real operational aggregation query and existing reconciliation path.
- Unit/property-oriented tests, PostgreSQL concurrency/integration tests, and GitHub Actions CI.
- ADR documentation for delivery semantics, ledger invariants, transactional outbox guarantees, ISO 20022 interoperability boundaries, and the AtlasPay/Nexus operator snapshot contract.

PostgreSQL payment/idempotency persistence is implemented. The in-memory adapter remains for isolated use. Schema ownership is explicit: migrations run separately from repository construction, are serialized with a PostgreSQL advisory lock, and reject checksum drift for already-applied versions. Payment operation atomicity covers database-local state, ledger mutation, operation record, and outbox persistence. External publication remains explicitly at-least-once: a crash after broker publication but before `published_at` commits can cause redelivery, so consumers must deduplicate or be idempotent. Reconciliation is deliberately observational: discrepancies are reported deterministically and repair actions are explicit, bounded controls rather than automatic accounting mutation. Network routing/correlation is transport-independent and does not imply issuer acceptance or successful external delivery. Network telemetry is currently process-local; the operator and analytics contracts therefore do not claim durable authorization-rate or issuer-latency history. Payment `status` is current mutable state, not a historical status event table, so analytics must not describe current status composition as a historical authorization/conversion funnel. No production deployment or live payment-network integration should be claimed unless independently verified.

## Engineering invariants

1. Never claim exactly-once delivery across external systems. Prefer at-least-once delivery plus idempotent consumers, durable constraints, and documented failure boundaries.
2. Payment amounts are represented in integer minor units. Do not introduce floating-point money arithmetic.
3. Idempotency must become durable before being described as production-grade. A retry with the same key and same request must be safe; conflicting reuse must fail explicitly.
4. Ledger entries must be append-only and double-entry balanced. Business state must not be reconstructed from mutable balance fields alone.
5. ISO 8583, EMV, and ISO 20022 are boundary protocols. Map them through a canonical internal payment model and document lossy mappings instead of leaking protocol-specific fields throughout the domain.
6. Unknown or malformed protocol fields should be rejected rather than guessed.
7. Prefer a modular monolith until measured constraints justify additional services.
8. Every consequential architecture choice should be captured in an ADR with guarantees, failure modes, and trade-offs.
9. Operational APIs fail closed, are observational by default, and distinguish unavailable measurements from measured zeroes.
10. Analytics must preserve currency in monetary grains, state the time/grain of every metric, label synthetic data as synthetic, and never manufacture historical facts from current-state tables.

## Priority build sequence

### 1. Durable persistence and idempotency

- [x] Introduce PostgreSQL payment persistence.
- [x] Add explicit versioned migrations with drift detection and deployment serialization.
- [x] Add durable idempotency records with unique constraints and request fingerprinting.
- [x] Add cross-worker concurrency tests for duplicate/replayed requests.
- [x] Enforce capture/refund/reversal payment state transitions in the PostgreSQL operation layer.

### 2. Double-entry ledger

- [x] Add accounts, journal transactions, and immutable debit/credit entries.
- [x] Enforce balanced transactions and currency consistency in PostgreSQL.
- [x] Add invariant and property tests for append-only, zero-sum, and currency behavior.
- [x] Make capture/refund/reversal flows post ledger entries atomically with business state.
- [x] Add replay-safe posting/idempotency semantics for business-operation linkage.

### 3. Transactional outbox and event delivery

- [x] Persist domain events in the same database transaction as state changes.
- [x] Add an outbox publisher and idempotent consumer examples.
- [x] Document at-least-once semantics, retry behavior, poison-message handling, and replay.
- [x] Add deterministic reconciliation and bounded replay tooling before broader Kafka topology.

### 4. Payment-network behavior

- [x] Add transport-independent STAN/RRN transaction coordination with explicit timeout, late-response, duplicate, and mismatch outcomes.
- [x] Add issuer/acquirer routing and one-to-one reversal correlation linkage.
- [x] Add explicit network adapters instead of embedding framing/network behavior in the core ISO 8583 codec.
- [x] Expand DE55 BER-TLV parsing, EMV tag dictionaries, and TVR decoding.
- [x] Add OpenTelemetry/Prometheus network observability with low-cardinality, non-sensitive labels.
- [x] Add deterministic network fault injection covering local failure, ambiguous timeout, and malformed response paths.

### 5. Interoperability

- [x] Add a scoped ISO 8583 -> canonical -> ISO 20022 authorization projection.
- [x] Document current lossy fields and fail-closed bridge behavior.
- [ ] Select a concrete ISO 20022 card-message family/version and add XML/XSD adapter validation before claiming wire-level conformance.

### 6. Operator/control-plane integration

- [x] Publish a versioned read-only AtlasPay operator snapshot contract for durable state.
- [x] Protect the operational API with fail-closed bearer authentication.
- [x] Verify real PostgreSQL aggregation and reconciliation paths in CI.
- [x] Have Nexus consume the AtlasPay API through a validated source adapter without silent fixture fallback.
- [ ] Add a durable source for network observations before exposing authorization-rate/issuer-latency metrics through the operator contract.

### 7. Data analytics and decision support

- [x] Add documented durable source grains and metric claim boundaries.
- [x] Add daily payment KPI/current-status composition mart by currency.
- [x] Add capture/refund/reversal lifecycle timing with p50/p95 elapsed time.
- [x] Add outbox delivery reliability and retry-limit mart.
- [x] Add daily ledger debit-credit balance control mart.
- [x] Execute analytics SQL against the migrated PostgreSQL schema in CI.
- [ ] Persist privacy-conscious authorization/network facts suitable for historical analytics.
- [ ] Add decline taxonomy, issuer performance, timeout/late-response cohorts, and reversal analytics after the fact source exists.
- [ ] Add a reproducible synthetic dataset generator and analyst-facing dashboard with metric definitions and decision narratives.

### 8. Production evidence

- [x] OpenTelemetry traces and Prometheus network metrics.
- [x] Deterministic network fault-injection tests.
- [ ] Structured audit logging without leaking sensitive values.
- [ ] Load/performance tests with documented methodology and non-fabricated measurements.
- [ ] Security checks beyond application bearer-token protection (TLS/workload identity/network policy/rate limits where a real deployment exists).
- [ ] Deployment only when CI is green and a real live URL can be verified.

## Relationship to other repositories

- `Nexus`: operator/control-plane UI for AtlasPay. It consumes the protected v1 snapshot in live mode when configured, preserves partial/unavailable semantics, fails closed rather than silently substituting fixtures, and should only expose network rates/latency after AtlasPay provides a durable verified source.
- `AtlasRAG`: separate production AI/LLM flagship focused on ingestion, hybrid retrieval, reranking, evaluation, groundedness, provider abstraction, token/cost/latency accounting, tenancy, jobs, security, and robust tests.
- `ForecastLab`: ICAO/passport-photo compliance CV/ML flagship with explainable per-rule scoring, pose/quality checks, versioned policy inference, and licensed held-out evaluation infrastructure without unverified real-world accuracy claims.
- `portfolio` and profile README: keep claims, links, deployment status, analytics role lenses, and project positioning synchronized with merged evidence.

## Runbook for future engineering passes

At the start of each pass:

1. Inspect `main`, recent commits, open PRs, and GitHub Actions.
2. Fix failing lint, tests, type checks, builds, security, or deployment regressions before adding features.
3. Read this file and relevant ADRs before changing architecture.
4. Pick the highest-value incomplete item from the priority sequence.
5. Make changes on a safe branch/PR when appropriate.
6. Re-run or inspect CI after changes and merge only green work when safe.
7. Update this file when the architectural state, guarantees, analytical grain, or next priority materially changes.

## Next highest-value task

Persist a privacy-conscious authorization/network fact source that records event time, route identifier, disposition, latency, timeout/late classification, and reversal linkage without PAN, DE55, or other sensitive payloads. Use that durable source to extend both the AtlasPay operator contract and the analytics warehouse with real authorization/issuer metrics. In parallel, keep concrete ISO 20022 XML/XSD validation and structured audit logging as the next protocol/security slices.
