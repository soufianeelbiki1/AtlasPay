# AtlasPay

AtlasPay is a payment-processing reference system built around failure handling, accounting correctness and protocol boundaries. It uses FastAPI and PostgreSQL and includes ISO 8583/EMV adapters, payment routing, idempotency, a double-entry ledger, a transactional outbox, reconciliation and an operational API consumed by Nexus.

It is a simulation: it does not connect to a live card network or process real money.

## Main components

- FastAPI payment lifecycle API.
- PostgreSQL persistence with request fingerprints, unique constraints and advisory locks for durable idempotency.
- Append-only double-entry ledger with balanced and currency-consistency checks.
- Atomic capture, refund and reversal operations that persist state, ledger entries and outbox events in one database transaction.
- Transactional outbox with bounded retries, poison-event retention and idempotent consumer examples.
- Read-only reconciliation across payments, operations, journals, ledger entries and outbox linkage.

## Payment protocols and network behavior

The ISO 8583 codec supports primary/secondary bitmaps plus fixed, LLVAR and LLLVAR fields. DE55 remains binary at the generic codec boundary and can be decoded by the EMV BER-TLV parser, including constructed templates and TVR interpretation.

Authorization messages map into a canonical model before routing or ISO 20022 projection. The network layer models accepted responses, correlation mismatches, duplicates, local failures, ambiguous timeouts and late responses. A timeout can trigger reversal correlation, but the code does not assume that a remote system failed simply because the local deadline expired.

Network observations can be persisted to PostgreSQL without storing PAN, STAN, RRN, DE55 or message payloads. The operator snapshot aggregates observation count, dispositions, timeout/late-response counts and p95 elapsed time from that durable source.

The current ISO 20022 work is a scoped authorization projection. It is not a general XML/XSD implementation or a certification claim.

## Operations and observability

AtlasPay exposes a protected read-only operator snapshot for Nexus. Payment, ledger, reconciliation, outbox and network summaries come from PostgreSQL when `DATABASE_URL` is configured.

Prometheus metrics and OpenTelemetry spans use low-cardinality labels and exclude PAN, STAN, RRN, DE55 and transaction identifiers.

## Local network demo

After migrating a local PostgreSQL database, run deterministic network scenarios:

```bash
export DATABASE_URL=postgresql://atlaspay:atlaspay@localhost:5432/atlaspay
python -m app.migrations
python -m app.demo_network --reset
```

The runner records four observations: an accepted response, an ambiguous timeout that creates reversal correlation, the late original response, and a known-local transport failure. It prints the same operational snapshot contract that Nexus consumes.

To expose that snapshot through the API:

```bash
export ATLASPAY_OPS_TOKEN=local-demo-token
uvicorn app.main:app --reload
```

Then configure Nexus with the AtlasPay base URL and the same token. The demo runner is intended for a local migrated database; `--reset` deletes existing network observations before inserting the deterministic scenarios.

## Analytics

`analytics/` contains PostgreSQL marts for:

- daily payment KPIs by currency;
- capture/refund/reversal lifecycle timing;
- outbox delivery reliability;
- daily debit/credit ledger controls.

The queries run against the migrated schema in CI. Current payment status is treated as current state, not as a historical authorization funnel, and monetary KPIs are never combined across currencies.

## Run locally

```bash
git clone https://github.com/soufianeelbiki1/AtlasPay.git
cd AtlasPay
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql://atlaspay:atlaspay@localhost:5432/atlaspay
python -m app.migrations
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for the API documentation.

## Tests

```bash
ruff check .
ruff format --check .
python -m compileall app tests
pytest
```

GitHub Actions provisions PostgreSQL and covers migrations, concurrency, persistence, reconciliation, network observation persistence, the deterministic network demo, operator aggregation and analytics SQL.

## Current limitations

- Network observations record operational metadata, not card/network payloads; they are not a historical ISO 8583 message archive.
- Network headers, TPDU framing, packed BCD profiles and scheme-specific transports are outside the current ISO 8583 codec.
- The ISO 20022 adapter does not yet validate a concrete card-message XSD.
- There is no verified live deployment or payment-network integration.

## Roadmap

1. Add per-route network aggregates and durable authorization facts suitable for deeper issuer analytics.
2. Add a concrete ISO 20022 message family with XML/XSD validation.
3. Add structured audit logging and reproducible performance tests.
4. Package AtlasPay and Nexus into a simpler local multi-service demo.

Architecture decisions and guarantee details are documented under `docs/adr/`.

## License

MIT
