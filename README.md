# AtlasPay

**Production-minded payment infrastructure, distributed-systems, and payments-analytics portfolio project.**

AtlasPay models the hard parts of payment systems: retries, durable idempotency, protocol boundaries, double-entry accounting, at-least-once event delivery, network ambiguity, reversals, reconciliation, observability, and analytical decision support.

> AtlasPay is an engineering simulation. It does not process real money, connect to live payment networks, or claim production scale.

## Why this project exists

Payment systems are difficult because a correct answer depends on more than a successful HTTP request. Clients retry. Messages duplicate. Network timeouts leave delivery ambiguous. Late responses arrive after local deadlines. Accounting must remain balanced. Events can be published twice. Operator dashboards must distinguish measured zeroes from data that is simply unavailable.

AtlasPay is built around those failure modes rather than around a CRUD demo.

## Implemented engineering evidence

### Payment domain and durable state

- FastAPI payment API with explicit payment lifecycle.
- Integer minor-unit money representation; no floating-point money arithmetic.
- PostgreSQL payment persistence and durable idempotency using request fingerprints, unique constraints, and advisory transaction locks.
- Ordered SQL migrations with checksum drift detection and serialized migration execution.
- Atomic capture/refund/reversal operations tying business state, operation records, ledger postings, and outbox events together inside one database transaction.

### Double-entry ledger and reconciliation

- Append-only debit/credit entries with immutable posted transactions.
- Database-enforced balanced-transaction and currency invariants.
- Replay-safe business-operation linkage.
- Deterministic read-only reconciliation across payments, operations, journals, ledger entries, and outbox linkage.
- Explicit bounded replay controls; published delivery history and ledger history are never silently rewritten.

### Event delivery

- Transactional outbox committed atomically with payment state.
- Database-backed publisher reference using `FOR UPDATE SKIP LOCKED`.
- Explicit at-least-once semantics, bounded retry accounting, and poison-message retention.
- Idempotent consumer claims keyed by `(consumer_name, event_id)`.
- No vague exactly-once claim across broker or network boundaries.

### ISO 8583, EMV, and ISO 20022

- Strict ISO 8583 message-body codec with primary/secondary bitmaps and fixed/LLVAR/LLLVAR validation.
- Binary DE55 support kept opaque at the generic ISO 8583 boundary.
- BER-TLV EMV decoding with constructed templates, duplicate-tag preservation, bounded nesting/length parsing, tag metadata, and explainable TVR decoding.
- Canonical authorization model with STAN/RRN correlation.
- Scoped ISO 8583 → canonical → ISO 20022 authorization projection with explicit mapping losses and fail-closed bridge constraints.
- No generic ISO 20022 XML/XSD or scheme-certification claim yet.

### Payment-network behavior

- Transport-independent issuer/acquirer routing with deterministic longest-prefix selection and currency eligibility.
- Explicit coordinator outcomes for accepted, mismatched, timed-out, late, and duplicate responses.
- Byte-oriented network transport port separated from the ISO 8583 codec.
- Timeout-triggered reversal correlation while preserving external delivery ambiguity.
- One-to-one original/reversal correlation with explicit reasons; correlation does not imply reversal delivery or acceptance.
- Deterministic fault injection for known-local failures, ambiguous timeouts, and malformed network responses.

### Observability and operator contract

- Low-cardinality Prometheus network metrics and exporter-neutral OpenTelemetry spans.
- PAN, STAN, RRN, DE55, and transaction identifiers are deliberately excluded from metric labels.
- Protected read-only `/v1/ops/snapshot` contract for Nexus.
- Durable payment, operation, reconciliation, and outbox measurements are aggregated from PostgreSQL.
- Non-durable network analytics are explicitly reported as unavailable rather than fabricated as zero.

## Payments Analytics Warehouse

The `analytics/` directory adds a decision-oriented SQL layer over AtlasPay's durable schema. It is designed as evidence for **Data Analyst / Analytics Engineer / Data Scientist** hiring as well as payment operations work.

Current marts:

- `analytics/sql/daily_payment_kpis.sql` — daily creation cohorts by currency, gross minor-unit amount, average ticket, and current durable status composition.
- `analytics/sql/payment_operation_latency.sql` — capture/refund/reversal counts plus average/p50/p95 elapsed time from payment creation to durable operation creation.
- `analytics/sql/outbox_reliability.sql` — published/unpublished/retry-limit event counts and average/p95 publish latency by day and event type.
- `analytics/sql/ledger_daily_balance.sql` — daily debit/credit totals and imbalance control by currency.

These queries are CI-tested against the migrated PostgreSQL schema. Their metric definitions and limitations are documented in [`analytics/README.md`](analytics/README.md).

Important claim boundary: `payments.status` is current state, not a historical state-event table, so the current status composition is **not** mislabeled as an authorization funnel. Likewise, operation timing is not issuer/network latency. Stronger issuer and authorization analytics will wait for a durable privacy-conscious network fact table.

## Architecture

```text
Clients / operator consumers
          |
          v
       FastAPI
          |
          +-------------------> protected operational snapshot
          |
          v
 payment application layer
          |
          +----> PostgreSQL payments + idempotency
          +----> immutable double-entry ledger
          +----> payment operations
          +----> transactional outbox
          |
          v
 canonical payment/network model
          |
   +------+------+----------------+
   |             |                |
ISO 8583        EMV           ISO 20022
adapter       DE55 parser     projection
   |
   v
transport / issuer routing / correlation

PostgreSQL durable state
          |
          v
 analytics SQL marts
```

The ISO 8583 codec covers the message body only. Network headers, TPDU framing, packed BCD variants, sockets/TLS, and network-specific profiles belong in explicit adapters. Unknown or malformed protocol values fail closed rather than being guessed.

## API example

```bash
curl -X POST http://localhost:8000/v1/payments \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: checkout-order-123" \
  -d '{
    "amount": 12900,
    "currency": "MAD",
    "merchant_reference": "order-123"
  }'
```

`amount` is expressed in the currency's minor unit (for example, `12900` means `129.00 MAD` for a two-decimal currency).

## Run locally

```bash
git clone https://github.com/soufianeelbiki1/AtlasPay.git
cd AtlasPay
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql://atlaspay:atlaspay@localhost:5432/atlaspay
python -m app.migrations
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for OpenAPI documentation.

## Quality gates

```bash
ruff check .
ruff format --check .
python -m compileall app tests
pytest
```

GitHub Actions also provisions PostgreSQL and exercises migrations, durable persistence, concurrency, reconciliation, operational-snapshot aggregation, and analytics SQL compatibility.

## Current next slices

- Persist a privacy-conscious authorization/network read model so Nexus and analytics can show real authorization outcomes, issuer-route health, timeouts/late responses, and latency history.
- Select a concrete ISO 20022 card-message family/version and add XML/XSD boundary validation before any wire-conformance claim.
- Add structured audit logging that avoids sensitive values.
- Add load/performance methodology with reproducible measurements rather than fake scale numbers.
- Extend the analytics warehouse with durable network facts, decline taxonomy, issuer cohorts, reversal analysis, and a deployable decision dashboard once the required data exists.

## Engineering principles

1. **State guarantees precisely.** Database atomicity, broker redelivery, network ambiguity, and operator availability are different guarantees.
2. **Fail closed.** Unsupported mappings and malformed inputs are rejected rather than coerced into plausible data.
3. **Keep money exact.** Monetary values use integer minor units and analytics never aggregate across currencies.
4. **Prefer durable invariants.** Unique constraints, append-only accounting, reconciliation, and idempotent consumers do more work than optimistic comments.
5. **Do not fabricate measurements.** Missing network history remains unavailable until a durable source exists.
6. **Use infrastructure for a reason.** The project stays modular rather than becoming decorative microservices.

## Documentation

Architecture decisions and guarantee boundaries live under `docs/adr/`. The continuously updated implementation state and next engineering priority are recorded in `PROJECT_CONTEXT.md`.

## Portfolio map

- AtlasPay: https://github.com/soufianeelbiki1/AtlasPay
- AtlasRAG: https://github.com/soufianeelbiki1/AtlasRAG
- ForecastLab: https://github.com/soufianeelbiki1/ForecastLab
- Nexus: https://github.com/soufianeelbiki1/Nexus
- Portfolio: https://github.com/soufianeelbiki1/portfolio

## License

MIT
