# ADR 0003: Transactional outbox and at-least-once delivery

## Status

Accepted.

## Context

Payment state, ledger journals, and externally visible domain events must not drift apart. Publishing directly to a broker inside the payment transaction would couple database availability to broker availability and still would not provide exactly-once delivery across the database/broker boundary.

## Decision

Capture, refund, and reversal operations write an `outbox_events` row in the same PostgreSQL transaction as the payment status change, ledger journal, and operation-idempotency record.

A separate publisher claims unpublished rows with `FOR UPDATE SKIP LOCKED`, invokes an external publisher, and marks successful rows as published. Failed attempts remain unpublished with an incremented attempt counter and the last error. Rows that reach the configured attempt ceiling are poison messages and require inspection/replay rather than being discarded.

Consumers deduplicate by `(consumer_name, event_id)` in PostgreSQL before applying their handler.

## Guarantees

- If a payment operation commits, its outbox event commits with it.
- If the database transaction rolls back, no event becomes eligible for publication.
- Operation idempotency prevents an exact operation replay from creating another event.
- Consumer processing is idempotent with respect to the same event id for a named consumer.

## Non-guarantees

Delivery is **at least once**, not exactly once. A publisher can successfully send to an external broker and crash before `published_at` is committed; the event will then be sent again after restart. Downstream consumers therefore must deduplicate or otherwise be idempotent.

The current implementation is a database-backed reference publisher. Kafka-specific producer configuration, partitioning, ordering, and broker-level retry policy are intentionally deferred until the event contract and replay behavior are stable.

## Failure handling

- transient publish failure: increment `attempts`, retain the event for retry;
- poison message: stop automatic attempts after the configured ceiling and inspect/replay explicitly;
- consumer crash after claim but before commit: the claim and handler transaction roll back together, allowing retry;
- duplicate consumer delivery: the durable consumed-event key turns the replay into a no-op.

## Consequences

This adds durable event-delivery state and makes failure semantics explicit while keeping AtlasPay a modular monolith. It also provides the foundation for reconciliation, replay tooling, Kafka integration, and operator views in Nexus without claiming impossible cross-system atomicity.
