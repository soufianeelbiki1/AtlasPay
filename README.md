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

The current ISO 20022 work is a scoped authorization projection. It is not a general XML/XSD implementation or a certification claim.

## Operations and observability

AtlasPay exposes a protected read-only operator snapshot for Nexus. Durable payment, ledger, reconciliation and outbox values come from PostgreSQL. Network metrics that are not persisted are reported as unavailable rather than converted to zero.

Prometheus metrics and OpenTelemetry spans use low-cardinality labels and exclude PAN, STAN, RRN, DE55 and transaction identifiers.

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

GitHub Actions provisions PostgreSQL and covers migrations, concurrency, persistence, reconciliation, operator aggregation and analytics SQL.

## Current limitations

- Authorization/network observations are process-local, so historical issuer latency and authorization-rate analytics are not exposed as durable metrics yet.
- Network headers, TPDU framing, packed BCD profiles and scheme-specific transports are outside the current ISO 8583 codec.
- The ISO 20022 adapter does not yet validate a concrete card-message XSD.
- There is no verified live deployment or payment-network integration.

## Roadmap

1. Persist privacy-conscious authorization/network observations for historical operations and analytics.
2. Add a concrete ISO 20022 message family with XML/XSD validation.
3. Add structured audit logging and reproducible performance tests.
4. Build a one-command AtlasPay + Nexus demo with timeout, duplicate and reversal scenarios.

Architecture decisions and guarantee details are documented under `docs/adr/`.

## License

MIT
