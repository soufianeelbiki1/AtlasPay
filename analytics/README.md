# AtlasPay Payments Analytics Warehouse

This directory turns AtlasPay's durable PostgreSQL state into a hiring-grade analytics layer for payment operations and decision support. It intentionally starts from tables AtlasPay really persists instead of inventing issuer, authorization, or production-scale metrics that do not yet exist durably.

## Business questions

1. How many payments are created each day, in each currency, and what is their current durable status mix?
2. How long after payment creation do capture, refund, and reversal operations occur?
3. Is the transactional outbox delivering events promptly, and where are unpublished or retry-limit events accumulating?
4. Do daily debit and credit postings remain balanced by currency?

These questions support operations triage, reconciliation, payment-lifecycle analysis, and reliability review. They do **not** yet answer issuer approval-rate or network-latency questions because AtlasPay's network telemetry is currently process-local and not stored as an analytical history.

## Source model

| Source | Grain | Important fields | Analytical use |
| --- | --- | --- | --- |
| `payments` | one payment | amount, currency, status, created_at | creation cohorts, amount distribution, current status mix |
| `payment_operations` | one idempotent lifecycle operation | operation, from_status, to_status, created_at | capture/refund/reversal volume and timing |
| `outbox_events` | one integration event | event_type, created_at, published_at, attempts | delivery backlog, retry-limit incidents, publish latency |
| `ledger_entries` | one debit/credit posting | transaction_id, side, amount, currency, created_at | daily debit-credit control totals |

Amounts are stored in **minor units**. Never aggregate monetary amounts across currencies.

## Marts

### `sql/daily_payment_kpis.sql`

Daily payment-creation cohort by currency with count, gross created amount, average ticket, and current durable status counts. `current_captured_share` is deliberately named as a **current-state composition metric**. Since `payments.status` is mutable current state rather than a status-history event table, it is not a historical authorization or conversion funnel.

### `sql/payment_operation_latency.sql`

Daily capture/refund/reversal observations by currency with count and average/p50/p95 time from payment creation to durable operation creation. This is lifecycle timing—not issuer latency, transport latency, or processing SLA.

### `sql/outbox_reliability.sql`

Daily outbox delivery health by event type: total, published, unpublished, retry-limit events, average/p95 publish latency, and maximum attempts. The retry-limit threshold is `attempts >= 5`, matching AtlasPay's current operator snapshot semantics.

### `sql/ledger_daily_balance.sql`

Daily debit and credit control totals by currency. `debit_credit_difference_minor` should be zero for balanced posted data. A non-zero value is an investigation signal; this analytics layer never repairs ledger state.

## Data-quality contracts

The CI integration test executes every mart against a migrated PostgreSQL schema and verifies its output columns. The marts also preserve these analytical invariants:

- currency is part of every monetary aggregation grain;
- current payment status is not mislabeled as historical funnel state;
- lifecycle operation timing is not mislabeled as network latency;
- unpublished outbox events are not counted as delivered;
- retry-limit events use the same threshold as operator reporting;
- ledger imbalance is surfaced rather than corrected.

## What a dashboard should show next

An analyst-facing layer can place these marts into four decision panels:

- **Payments:** created volume, gross minor-unit amount, average ticket, current status composition, currency filter;
- **Lifecycle:** capture/refund/reversal counts and p50/p95 elapsed time;
- **Reliability:** unpublished backlog, retry-limit events, publish latency trend, event-type breakdown;
- **Accounting controls:** debit vs credit totals and any non-zero daily/currency differences.

The dashboard should link each metric to its definition and limitation rather than presenting unexplained KPIs.

## Next analytical schema slice

To answer stronger payment-performance questions, AtlasPay should persist a privacy-conscious authorization/network fact table with event time, issuer route identifier, disposition, latency, timeout/late-response classification, and reversal linkage—without PAN, DE55, or high-cardinality sensitive payloads. Once durable, that fact can support authorization-rate, decline taxonomy, issuer performance, timeout cohorts, and reversal analysis without pretending process-local Prometheus metrics are historical warehouse data.

## Evidence and claim boundary

The repository currently contains application/dev data and deterministic test data, not a production merchant dataset. Any generated demonstration dataset must be labeled synthetic. No business finding, revenue figure, issuer performance claim, or production scale claim should be stated until a reproducible dataset actually supports it.
