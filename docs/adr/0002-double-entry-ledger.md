# ADR 0002: PostgreSQL double-entry ledger invariants

## Status

Accepted for the first ledger foundation.

## Context

AtlasPay needs an auditable monetary record that remains correct under retries, process restarts,
and later replay/reconciliation work. Mutable balance columns are insufficient because they hide
history and make reconstruction difficult.

## Decision

The ledger is append-only and stored in PostgreSQL using three concepts:

- ledger accounts, each bound to one 3-letter currency;
- journal transactions, each bound to one currency and reference;
- debit/credit entries with strictly positive integer minor-unit amounts.

A journal transaction is valid only when it contains at least one debit and one credit and total
debits equal total credits.

Currency consistency is enforced with composite foreign keys from entries to both the journal
transaction and account. Balance validation is enforced by a DEFERRABLE INITIALLY DEFERRED
constraint trigger, so all postings can be inserted in one database transaction before the
invariant is checked at commit.

Posted entries and journal metadata are immutable. Corrections must be represented by new
compensating/reversal transactions rather than UPDATE or DELETE.

## Guarantees

Within one PostgreSQL transaction boundary:

1. either the journal transaction and every posting commit, or none commit;
2. committed journals are balanced;
3. every posting uses the journal and account currency;
4. posting amounts are positive integer minor units;
5. posted entries and journal metadata cannot be mutated in place.

## Non-guarantees

This ledger does not provide exactly-once semantics across payment networks, Kafka, webhooks, or
other external systems. Those boundaries require durable idempotency keys, at-least-once delivery,
reconciliation, and explicit replay semantics.

This first slice also does not yet bind capture/refund/reversal state changes atomically to ledger
posting. That integration is the next step after the core journal invariants are proven.

## Consequences

The database, not only Python code, protects core accounting invariants. This adds PostgreSQL
trigger complexity but prevents alternate writers from bypassing the balance rule. Queries derive
balances from immutable entries; materialized balances may be introduced later only as rebuildable
read models.
