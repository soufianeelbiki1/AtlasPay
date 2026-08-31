# AtlasPay

AtlasPay is a payment-processing reference system built around failure handling, accounting correctness and protocol boundaries. It uses FastAPI and PostgreSQL and includes ISO 8583/EMV adapters, payment routing, idempotency, a double-entry ledger, a transactional outbox, reconciliation and an operational API consumed by Nexus.

It is a simulation: it does not connect to a live card network or process real money.

## Java authorization boundary

The `java-service/` module is a Java 21 / Spring Boot 3 authorization boundary beside the Python API. It validates requests, persists an authorization decision and `authorization.decided` outbox event in one PostgreSQL transaction, and uses a unique Idempotency-Key constraint to make retries return the original decision. It exposes Actuator health and Prometheus-compatible metrics and includes a non-root container image plus a dedicated Maven CI workflow. Event delivery is at-least-once; no cross-system exactly-once claim is made.

Run it with PostgreSQL using `mvn -f java-service/pom.xml spring-boot:run`. This simulation deterministically declines amounts above 1,000,000 minor units; it is not an issuer integration.

## Main components

- FastAPI payment lifecycle API.
- Java 21/Spring Boot authorization boundary with PostgreSQL and transactional outbox.
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

## Analytics

`analytics/` contains PostgreSQL marts for daily payment KPIs, lifecycle timing, outbox delivery reliability and ledger controls. Queries run against the migrated schema in CI and never combine monetary KPIs across currencies.

## Run locally

```bash
git clone https://github.com/soufianeelbiki1/AtlasPay.git
cd AtlasPay
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql://atlaspay:atlaspay@localhost:5432/atlaspay
python -m app.migrations
uvicorn app.main:app --reload
mvn -f java-service/pom.xml spring-boot:run
```

Open `http://localhost:8000/docs` for the Python API and `http://localhost:8080/actuator/health` for the Java readiness endpoint.

## Current limitations

- No verified live deployment or payment-network integration.
- Network observations record operational metadata, not a historical ISO 8583 message archive.
- The ISO 20022 adapter does not yet validate a concrete card-message XSD.

Architecture decisions and guarantee details are documented under `docs/adr/`.

## License

MIT
