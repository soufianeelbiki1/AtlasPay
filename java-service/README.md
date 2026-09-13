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
these four fields, including the absence of writes. PostgreSQL arbitrates
simultaneous first requests using the unique idempotency key and
`INSERT ... ON CONFLICT DO NOTHING`. The losing transaction rereads the
committed decision under explicit READ COMMITTED isolation and applies the same
request comparison; it never emits another event.

`AuthorizationPostgresTest` uses a disposable local PostgreSQL 16 Testcontainer
and the real Spring transaction proxy. A test-only barrier forces both first
reads to observe no existing decision. The tests assert one decision and one
event for identical concurrent requests, one success and one conflict for
changed concurrent requests, and transaction rollback when outbox insertion
fails. Run `mvn -B test` with Java 21 and Docker. No hosted database or API
credentials are used. This covers the authorization boundary, not a claim of
whole-system exactly-once delivery or a production benchmark.
The payment flows are simulations and do not move real money.

## Reconciliation batch

POST /reconciliation/runs launches a restartable Spring Batch job. It reads unprocessed reconciliation_items in chunks of 100 and upserts results into reconciliation_results. Spring Batch metadata in PostgreSQL provides restartability; rerunning a completed item is idempotent because the result key is the item UUID. The job uses at-least-once processing: a crash after writing a result but before marking the source row processed can cause a re-read, which is safe due to the upsert key. Match status is deliberately limited to MATCHED/MISMATCH; settlement policy remains outside this component.

The service exposes Actuator health and Prometheus metrics. Configure DATABASE_URL, DB_USER, and DB_PASSWORD for PostgreSQL.
