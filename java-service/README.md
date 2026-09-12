# AtlasPay authorization service

Java 21 / Spring Boot 3 service for the narrow authorization boundary.

## Authorization retries

`POST /v1/authorizations` requires an internal bearer token and an
`Idempotency-Key` header. After a decision is persisted, an identical retry
returns the original decision ID without inserting another decision or outbox
event. Reusing the key with a different payment ID, issuer ID, amount in minor
units, or currency returns HTTP 409. Clients must not reinterpret the original
decision as authorization for the changed request.

`AuthorizationServiceTest` checks identical replay and conflicts for each of
these four fields, including the absence of writes. These are mocked service
tests, not proof of concurrent database behavior. Concurrent first requests
still rely on the database unique constraint; a transactional concurrency
integration test and graceful handling of that race remain follow-up work.
The payment flows are simulations and do not move real money.

## Reconciliation batch

POST /reconciliation/runs launches a restartable Spring Batch job. It reads unprocessed reconciliation_items in chunks of 100 and upserts results into reconciliation_results. Spring Batch metadata in PostgreSQL provides restartability; rerunning a completed item is idempotent because the result key is the item UUID. The job uses at-least-once processing: a crash after writing a result but before marking the source row processed can cause a re-read, which is safe due to the upsert key. Match status is deliberately limited to MATCHED/MISMATCH; settlement policy remains outside this component.

The service exposes Actuator health and Prometheus metrics. Configure DATABASE_URL, DB_USER, and DB_PASSWORD for PostgreSQL.
