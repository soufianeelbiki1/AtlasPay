# AtlasPay

**Production-minded payment orchestration API built to demonstrate reliable fintech backend engineering.**

AtlasPay is a portfolio-grade backend project for creating and tracking payment intents while modeling the engineering concerns that real payment systems face: **idempotency, explicit state transitions, auditability, failure handling, and clean API contracts**.

> This repository is an engineering project and simulation. It does not process real money or connect to live payment networks.

## Why this project exists

Payment systems are deceptively difficult. A reliable backend must remain correct when clients retry requests, providers time out, events arrive twice, and services restart halfway through a transaction.

AtlasPay is designed around those problems rather than around a simple CRUD demo.

## Current MVP

- FastAPI REST API
- Create payment intents
- Retrieve payment state
- Explicit payment lifecycle (`pending`, `authorized`, `captured`, `failed`, `cancelled`)
- Idempotency-key support at the service layer
- Decimal-safe money representation using integer minor units
- Domain validation with Pydantic
- Unit tests for payment creation and idempotency
- Strict ISO 8583 message codec with primary/secondary bitmaps, LLVAR/LLLVAR validation, and binary DE55 support
- Docker-ready application

## Architecture

```text
Client
  |
  v
FastAPI routes
  |
  v
Payment service  ----> Idempotency registry
  |
  v
Payment repository
  |
  v
Domain models

ISO 8583 transport adapters use the explicit codec profile at the network boundary.
```

The first version intentionally uses an in-memory repository so the domain behavior stays easy to understand and test. The roadmap evolves it toward PostgreSQL, an immutable ledger, asynchronous events, webhooks, observability, and provider adapters.

The ISO 8583 codec currently covers the message body only: ASCII MTI, binary
primary/secondary bitmaps, and ASCII LLVAR/LLLVAR length prefixes. Network
headers, TPDU framing, packed BCD variants, and network-specific field
profiles belong in explicit adapters. Unknown fields and malformed values are
rejected rather than guessed.

Delivery guarantees and failure boundaries are documented in
[`docs/adr/0001-delivery-semantics.md`](docs/adr/0001-delivery-semantics.md).

## API example

### Create a payment

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

Example response:

```json
{
  "id": "pay_...",
  "amount": 12900,
  "currency": "MAD",
  "merchant_reference": "order-123",
  "status": "pending"
}
```

`amount` is expressed in the currency's **minor unit** (for example, 12900 = 129.00 MAD).

## Run locally

```bash
git clone https://github.com/soufianeelbiki1/AtlasPay.git
cd AtlasPay
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Then open `http://localhost:8000/docs` for the interactive OpenAPI documentation.

## Run tests

```bash
pytest
```

## Docker

```bash
docker build -t atlaspay .
docker run -p 8000:8000 atlaspay
```

## Engineering roadmap

- [x] Payment domain model and REST API
- [x] Idempotent payment creation
- [x] Unit tests
- [x] Strict ISO 8583 MTI/bitmap/field codec and property-based round-trip tests
- [ ] PostgreSQL persistence with migrations
- [ ] Double-entry ledger
- [ ] Payment state-machine enforcement
- [ ] Provider adapter interface and sandbox provider
- [ ] Transactional outbox + asynchronous event processing
- [ ] Signed webhook delivery with retries
- [ ] Redis-backed rate limiting / idempotency cache
- [ ] OpenTelemetry traces and Prometheus metrics
- [x] CI with GitHub Actions
- [ ] Load tests and failure-injection tests
- [ ] Architecture decision records (ADRs)

## What this demonstrates

AtlasPay is meant to make engineering skills visible to recruiters and research/graduate reviewers:

- API design and backend architecture
- Correctness under retries
- Domain-driven modeling
- Testability and separation of concerns
- Distributed-systems thinking
- Fintech-specific reliability concerns
- Production-oriented documentation

## License

MIT

## Portfolio continuity contract

This repository is the payments and distributed-systems flagship in the soufianeelbiki1 portfolio. Future work must begin by inspecting the latest repository state and CI, then fixing regressions before adding capability.

### Build sequence

1. Strict ISO 8583 MTI, primary/secondary bitmap, fixed/LLVAR/LLLVAR field codecs with validation and property-based round-trip tests.
2. STAN/RRN correlation, issuer/acquirer routing, timeout and late-response handling, duplicate detection, and reversals.
3. DE55 BER-TLV parsing, EMV tag dictionaries, TVR decoding, and a canonical internal payment model.
4. ISO 8583 ↔ canonical model ↔ ISO 20022 mappings with documented lossy fields and explicit failure semantics.
5. Durable idempotency, PostgreSQL constraints, double-entry ledger, transactional outbox, and replay/rebuild.
6. Kafka/event streaming, at-least-once delivery with idempotent consumers, reconciliation, settlement hooks, observability, security, fault injection, and load tests.

Nexus is the later operator/control-plane UI and should consume real AtlasPay operational data. Do not claim exactly-once behavior across external boundaries; document the actual guarantees and failure boundaries. Avoid fake scale claims, toy abstractions, and unnecessary microservices. Record consequential choices as ADRs.

### Portfolio map

- AtlasPay: https://github.com/soufianeelbiki1/AtlasPay
- AtlasRAG: https://github.com/soufianeelbiki1/AtlasRAG
- ForecastLab: https://github.com/soufianeelbiki1/ForecastLab
- Nexus: https://github.com/soufianeelbiki1/Nexus
- Portfolio: https://github.com/soufianeelbiki1/portfolio

Status snapshot (2026-08-29): AtlasPay is the main working codebase; AtlasRAG has architecture documentation; the remaining repositories are being built out. No deployment is claimed until a live URL is verified.
