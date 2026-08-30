# AtlasPay Project Context

## Portfolio role

AtlasPay is the flagship payments and distributed-systems project in the `soufianeelbiki1` portfolio. It should demonstrate correctness under retries, explicit failure semantics, protocol interoperability, durable state, ledgering, event delivery, observability, and production-minded trade-offs without claiming fake scale or impossible exactly-once guarantees across external boundaries.

## Current state

As of 2026-08-30, the repository already contains:

- FastAPI payment-intent API and explicit payment lifecycle.
- Durable PostgreSQL idempotency with request fingerprinting and a unique database key.
- Decimal-safe money modeling using integer minor units.
- Strict ISO 8583 codec support with primary/secondary bitmaps, fixed/LLVAR/LLLVAR validation, and binary DE55 handling.
- Protocol-independent canonical authorization models.
- ISO 8583 mapping plus MTI/STAN/RRN correlation groundwork.
- Versioned SQL migrations with checksum drift detection and a PostgreSQL advisory migration lock.
- Unit/property-oriented tests, PostgreSQL concurrency tests, and GitHub Actions CI.
- ADR documentation for delivery semantics and failure boundaries.

PostgreSQL payment/idempotency persistence is implemented. The in-memory adapter remains for isolated use. Schema ownership is explicit: migrations run separately from repository construction, are serialized with a PostgreSQL advisory lock, and reject checksum drift for already-applied versions. No production deployment or live payment-network integration should be claimed unless independently verified.

## Engineering invariants

1. Never claim exactly-once delivery across external systems. Prefer at-least-once delivery plus idempotent consumers, durable constraints, and documented failure boundaries.
2. Payment amounts are represented in integer minor units. Do not introduce floating-point money arithmetic.
3. Idempotency must become durable before being described as production-grade. A retry with the same key and same request must be safe; conflicting reuse must fail explicitly.
4. Ledger entries must be append-only and double-entry balanced. Business state must not be reconstructed from mutable balance fields alone.
5. ISO 8583, EMV, and ISO 20022 are boundary protocols. Map them through a canonical internal payment model and document lossy mappings instead of leaking protocol-specific fields throughout the domain.
6. Unknown or malformed protocol fields should be rejected rather than guessed.
7. Prefer a modular monolith until measured constraints justify additional services.
8. Every consequential architecture choice should be captured in an ADR with guarantees, failure modes, and trade-offs.

## Priority build sequence

### 1. Durable persistence and idempotency

- [x] Introduce PostgreSQL payment persistence.
- [x] Add explicit versioned migrations with drift detection and deployment serialization.
- [x] Add durable idempotency records with unique constraints and request fingerprinting.
- [x] Add cross-worker concurrency tests for duplicate/replayed requests.
- [ ] Enforce payment state transitions in the domain and database-facing service layer.

### 2. Double-entry ledger

- Add accounts, journal transactions, and immutable debit/credit entries.
- Enforce balanced transactions and currency consistency.
- Make capture/refund/reversal flows post ledger entries atomically with business state.
- Add property/invariant tests for ledger balancing and replay safety.

### 3. Transactional outbox and event delivery

- Persist domain events in the same database transaction as state changes.
- Add an outbox publisher and idempotent consumer examples.
- Document at-least-once semantics, retry behavior, poison-message handling, and replay.
- Add reconciliation/rebuild tooling before introducing broader Kafka topology.

### 4. Payment-network behavior

- Continue STAN/RRN correlation, issuer/acquirer routing, timeout handling, late responses, duplicate detection, and reversals.
- Add explicit network adapters instead of embedding framing/network behavior in the core ISO 8583 codec.
- Expand DE55 BER-TLV parsing, EMV tag dictionaries, and TVR decoding.

### 5. Interoperability

- Complete ISO 8583 -> canonical model -> ISO 20022 mappings.
- Document fields that cannot be mapped losslessly and define explicit rejection/fallback behavior.

### 6. Production evidence

- OpenTelemetry traces and Prometheus metrics.
- Structured audit logging without leaking sensitive values.
- Fault-injection tests, load tests, security checks, and meaningful SLO-oriented measurements.
- Deployment only when CI is green and a real live URL can be verified.

## Relationship to other repositories

- `Nexus`: operator/control-plane UI for AtlasPay. It should eventually consume real AtlasPay operational data such as transaction flows, issuer latency, authorization rates, reversals, ledger/reconciliation status, Kafka lag, incidents, topology, and transaction drill-downs.
- `AtlasRAG`: separate production AI/LLM flagship focused on ingestion, hybrid retrieval, reranking, evaluation, groundedness, provider abstraction, cost/latency tracing, tenancy, jobs, security, and robust tests.
- `ForecastLab`: transitioning into an ICAO passport-photo compliance CV/ML flagship with explainable per-rule scoring, pose/quality/segmentation checks, evaluation/versioning, FastAPI inference, and polished demo UI.
- `portfolio` and profile README: keep claims, links, deployment status, and project positioning synchronized.

## Runbook for future engineering passes

At the start of each pass:

1. Inspect `main`, recent commits, open PRs, and GitHub Actions.
2. Fix failing lint, tests, type checks, builds, security, or deployment regressions before adding features.
3. Read this file and relevant ADRs before changing architecture.
4. Pick the highest-value incomplete item from the priority sequence.
5. Make changes on a safe branch/PR when appropriate.
6. Re-run or inspect CI after changes and merge only green work when safe.
7. Update this file when the architectural state, guarantees, or next priority materially changes.

## Next highest-value task

Implement the append-only double-entry ledger on PostgreSQL: accounts, journal transactions, debit/credit entries, balanced-transaction and currency invariants, plus transactional/property tests. Keep postings atomic with the business operation that creates them.
