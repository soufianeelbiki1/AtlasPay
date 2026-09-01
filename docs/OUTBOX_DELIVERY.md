# Outbox delivery semantics

AtlasPay uses a transactional outbox to keep domain state and event creation in the same database transaction.

The delivery path is intentionally split into three phases:

1. Claim unpublished events with row-level locking and an expiring lease.
2. Publish outside the database transaction so a slow broker or webhook does not hold database locks.
3. Acknowledge successful delivery or record a bounded error and release the lease.

If a worker crashes after claiming an event, a later worker can reclaim it after the lease expires. If a worker crashes after external publication but before acknowledgement, the event may be delivered again. This is the intended at-least-once guarantee; consumers deduplicate using consumer name plus event ID.

Events that reach the maximum attempt count remain unpublished with their last error for operator inspection. Reset and replay are explicit operations rather than silent data mutation.

This design is suitable for a Railway worker or scheduled service and can later be connected to a broker or signed webhook adapter without changing the transaction boundary.
