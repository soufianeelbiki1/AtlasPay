# ADR 0001: Delivery semantics across payment boundaries

- Status: Accepted
- Date: 2026-08-29
- Scope: AtlasPay payment commands, provider integrations, and emitted events

## Context

AtlasPay crosses boundaries that cannot share one database transaction: an API
client, an issuer/acquirer or provider, a database, and an event broker. A
timeout can happen after a remote system accepted a request, and a broker can
redeliver an event after a consumer committed its business result.

Calling that whole path “exactly once” would hide those failure boundaries and
would be misleading. A local transaction can be atomic, but an external side
effect cannot be rolled back by AtlasPay after the network boundary has been
crossed.

## Decision

AtlasPay will document guarantees at the boundary where they are enforceable:

1. API idempotency keys are durable records in the same database transaction as
   the payment intent. A retry with the same key and a different request is a
   conflict.
2. Payment state changes and outbox records are committed atomically in the
   AtlasPay database. Outbox publication is at-least-once.
3. Consumers are at-least-once and idempotent. A database uniqueness
   constraint, such as `(consumer_name, event_id)`, is the final duplicate
   guard; in-memory deduplication is only an optimization.
4. Provider calls use correlation identifiers, bounded timeouts, duplicate
   detection, and explicit late-response/reversal handling. A timeout means
   “outcome unknown”, not “declined”.
5. Replays rebuild projections or derived views from an immutable event/ledger
   history. They do not silently re-run external provider side effects.

## Consequences

- “Exactly once” may only be used for a specifically scoped local database
  transaction if its invariants and failure behavior are shown.
- The system must expose duplicate, timeout, late-response, and reconciliation
  states instead of collapsing them into success/failure.
- Reliability tests will inject failures between database commit, broker
  publication, consumer commit, and provider response handling.
