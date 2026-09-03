# Portfolio engineering context

Last verified: 2026-09-03
Canonical portfolio: Payments & Distributed Systems, Applied AI/ML, and Full-Stack Product Engineering.

## Repository roles

- **AtlasPay** is the flagship payment-infrastructure simulation: ISO 8583/EMV boundaries, canonical payment state, issuer routing, timeout/late-response handling, duplicate detection, reversals, PostgreSQL idempotency, double-entry ledger, transactional outbox, reconciliation and operational telemetry.
- **Nexus** is the Next.js/TypeScript operator console for AtlasPay. It validates a versioned snapshot and shows ready, stale, partial or unavailable states without inventing live data.
- **AtlasRAG** is the applied-LLM system: ingestion, hybrid retrieval, citations, provider accounting and versioned regression evaluation.
- **ForecastLab** is transitioning from generic forecasting into an ICAO passport-photo compliance computer-vision flagship; current rules operate on explicit observations and remain explainable.
- **portfolio** and **soufianeelbiki1** are the public demo hub and profile README. They must describe implemented behavior and link to the same live demos.

## Current verified state

- AtlasPay main is at 741465a (Unify Java authorization with AtlasPay schema); its Python CI, Java service CI and Railway deployment checks are green.
- AtlasPay production has separate Python and Java Railway services using the shared PostgreSQL schema. The hosted demo is deterministic and does not process real money or connect to a live card network.
- Nexus main is at e227659 (Document verified AtlasPay cloud topology); GitHub CI and the Vercel production deployment are green. The live console reads the protected AtlasPay snapshot through the server-side bearer-token boundary.
- The live demo intentionally exposes operational facts and failure states, not PAN, message payloads, STAN/RRN, DE55 or transaction identifiers.
- AtlasRAG, ForecastLab and portfolio each have green latest default-branch CI as of this verification. The profile README is synchronized with the portfolio positioning.

## Guarantees and failure boundaries

- Database uniqueness and transactions provide durable idempotency inside PostgreSQL; external delivery remains at-least-once.
- A local timeout means delivery is unknown, not that the issuer declined or failed. Late responses and reversals are correlated explicitly.
- Ledger entries must balance and remain currency-consistent. Reconciliation is read-only and reports discrepancies.
- The outbox closes the database-to-publisher atomicity gap but does not make Kafka or any external network exactly-once.
- ISO 8583 and ISO 20022 mappings are intentionally scoped and may be lossy; no certification claim is made.

## Working order

1. Keep default-branch CI, container hardening, security checks and deployment health green.
2. Close protocol and accounting correctness gaps with executable tests and documented invariants.
3. Extend durable operational contracts before adding UI-only metrics.
4. Prefer a modular monolith and explicit failure semantics; avoid fake scale claims and unnecessary services.
5. Keep README, live deployment notes, portfolio demos and profile identity synchronized.

## Highest-value next tasks

- Extend the operational contract with issuer/route breakdowns and durable transaction drill-down facts.
- Add controlled outbox replay/rebuild tooling with audit records and idempotent-consumer constraints.
- Add a concrete, versioned EMV tag dictionary and broader TVR rule coverage.
- Add AtlasRAG groundedness/recall evaluation metrics and ForecastLab pixel-level inference adapters only when their datasets and limitations are explicit.
