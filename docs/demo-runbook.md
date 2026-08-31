# AtlasPay senior interview demo runbook

This runbook is for a local, synthetic demonstration of AtlasPay's durable payment behavior. It is not a production benchmark and does not connect to a real card network.

## What the demo proves

The demo is designed to make the following engineering behavior visible in a few minutes:

1. durable payment creation in PostgreSQL;
2. idempotent replay returning the original payment;
3. captured, refunded, reversed, failed, and pending operator states;
4. balanced ledger postings for durable operations;
5. outbox events committed with capture/refund/reversal operations;
6. protected operator snapshots consumed by Nexus;
7. explicit boundaries where authorization/network history is not yet durable.

## Seed the demo

After migrations are applied and `DATABASE_URL` is configured:

```bash
python -m app.demo_seed
```

The command prints a JSON manifest containing the synthetic run id, payment ids, operation ids, and the assumptions used by the seed.

The seeder is append-only: each run creates a new synthetic scenario rather than deleting prior durable history.

## Idempotency story

The seeder sends the same payment creation request twice with the same idempotency key and verifies that both attempts resolve to the same durable payment id.

In an interview, explain the distinction between:

- API/client retries;
- database uniqueness/serialization protecting the idempotency claim;
- broker/network delivery semantics, which are separate guarantees.

Do not describe external delivery as exactly-once.

## Operation story

The capture/refund/reversal examples use `PostgresPaymentOperations`, so payment state, ledger transaction, ledger entries, operation record, and outbox event commit in one PostgreSQL transaction.

The seed directly establishes `authorized` or `failed` starting states only because AtlasPay does not yet persist a complete authorization-network fact stream. That limitation is deliberate and documented rather than replaced with fake issuer telemetry.

## Show the operator state

With `ATLASPAY_OPS_TOKEN` configured:

```bash
curl http://localhost:8000/v1/ops/snapshot \
  -H "Authorization: Bearer $ATLASPAY_OPS_TOKEN"
```

Then open Nexus and verify that the same durable payment, ledger, outbox, and reconciliation state is rendered through its authenticated AtlasPay source.

## Failure discussion

Use the existing network coordinator/fault-injection tests to discuss ambiguous timeout, late response, duplicate response, and reversal-correlation behavior. Those deterministic network simulations are intentionally separate from the durable demo seed until AtlasPay has a durable authorization/network history model.

## Senior-level discussion prompts

- Why is payment idempotency not the same guarantee as exactly-once message delivery?
- Which state changes must commit atomically with ledger entries and outbox events?
- What happens if a local timeout occurs after a remote issuer actually accepted a request?
- Why does Nexus render unavailable network metrics instead of zero?
- Which data would be safe to persist for issuer analytics without storing PAN or DE55?

These questions are part of the demo because architecture trade-offs and guarantee boundaries are more important than a scripted happy path.
