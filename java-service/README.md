# AtlasPay authorization service

Java 21 / Spring Boot 3 service for the narrow authorization boundary.

## Reconciliation batch

POST /reconciliation/runs launches a restartable Spring Batch job. It reads unprocessed reconciliation_items in chunks of 100 and upserts results into reconciliation_results. Spring Batch metadata in PostgreSQL provides restartability; rerunning a completed item is idempotent because the result key is the item UUID. The job uses at-least-once processing: a crash after writing a result but before marking the source row processed can cause a re-read, which is safe due to the upsert key. Match status is deliberately limited to MATCHED/MISMATCH; settlement policy remains outside this component.

The service exposes Actuator health and Prometheus metrics. Configure DATABASE_URL, DB_USER, and DB_PASSWORD for PostgreSQL.