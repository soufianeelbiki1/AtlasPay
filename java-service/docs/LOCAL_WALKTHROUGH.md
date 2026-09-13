# Inspect the Java authorization boundary locally

This is a **synthetic payment simulation**, not an issuer integration. No real
money moves. Everything below runs on your own machine; do not use hosted
database credentials or a production bearer token.

## Fastest verification path

Prerequisites: Java 21, Maven, and a running local Docker engine. From the
repository root:

```sh
cd java-service
mvn -B -Dtest=AuthorizationHttpPostgresTest,AuthorizationPostgresTest test
```

The HTTP suite boots the real Spring application on a random local port and a
disposable PostgreSQL 16 container. It verifies responses **and database state**:

| Scenario | HTTP result | Stored decisions / events |
| --- | --- | --- |
| First valid request, then identical retry | 200; same decision ID and response | 1 / 1 |
| Changed amount with the same key | 409; original amount and ID retained | Still 1 / 1 |
| Missing bearer credentials | 401 | 0 / 0 |
| Zero amount with valid credentials | 400 | 0 / 0 |
| Invalid currency/identifiers, then corrected input with the same key | 400, then 200 | 0 / 0, then 1 / 1 |
| Invalid retry after a valid decision | 400 | Still 1 / 1 |
| 129-character key / valid 128-character boundary | 400 / 200 | 0 / 0 or 1 / 1 |
| Amount above the simulated limit | 200 with `declined` / `amount_limit` | 1 / 1 |

The separate transaction suite forces overlapping first reads, verifies identical
and conflicting concurrent requests, and checks rollback when the outbox write
fails. The HTTP suite uses the outbox columns consumed by this boundary, not an
event publisher, consumer, or entire payment platform. Docker is required; these
tests must fail rather than silently skip when it is unavailable.

## Manual request walkthrough

Use a dedicated, disposable database. Commands in this section start at the
repository root. The database is bound only to loopback, uses demo credentials,
and has no persistent volume. If the chosen container name or port already
exists, choose a different one; do not stop unrelated infrastructure.

```sh
docker run --rm --name atlaspay-java-walkthrough \
  -e POSTGRES_DB=atlaspay -e POSTGRES_USER=atlaspay -e POSTGRES_PASSWORD=atlaspay \
  -p 127.0.0.1:55432:5432 -d postgres:16-alpine
docker exec atlaspay-java-walkthrough pg_isready -U atlaspay -d atlaspay
```

Repeat the readiness check until it reports accepting connections. Initialize
the shared outbox from the authoritative root migration, **once for this fresh
database**. Spring initializes its authorization/reconciliation tables on start.

```sh
docker exec -i atlaspay-java-walkthrough psql -v ON_ERROR_STOP=1 \
  -U atlaspay -d atlaspay < migrations/004_transactional_outbox.sql
cd java-service
mvn -B -DskipTests package
SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:55432/atlaspay \
  SPRING_DATASOURCE_USERNAME=atlaspay SPRING_DATASOURCE_PASSWORD=atlaspay \
  ATLASPAY_INTERNAL_TOKEN=local-walkthrough-not-a-secret PORT=18080 \
  java -jar target/authorization-service-0.1.0.jar
```

In a second terminal, send this request twice:

```sh
curl -i http://127.0.0.1:18080/v1/authorizations \
  -H 'Authorization: Bearer local-walkthrough-not-a-secret' \
  -H 'Idempotency-Key: walkthrough-1' -H 'Content-Type: application/json' \
  --data '{"paymentId":"pay-local-1","issuerId":"issuer-local-1","amountMinor":1234,"currency":"EUR"}'
```

Both responses should be HTTP 200 with the same generated `decisionId`. Keep the
key and change `amountMinor` to `1235`: expect HTTP 409. Remove Authorization:
expect HTTP 401. Use a fresh key and an amount of zero: expect HTTP 400. Use a
fresh key and `1000001`: expect a transport success (HTTP 200), but a business
decision of `declined`. This hard-coded threshold is demo policy, not fraud or
issuer risk modeling.

Inspect persistence after just the first two identical requests and conflict:

```sh
docker exec atlaspay-java-walkthrough psql -U atlaspay -d atlaspay -c \
  "SELECT decision_id, idempotency_key, amount_minor, status FROM authorization_decisions;"
docker exec atlaspay-java-walkthrough psql -U atlaspay -d atlaspay -c \
  "SELECT aggregate_id, event_type, payload FROM outbox_events;"
```

Expect one decision at `1234` and one `authorization.decided` event. UUIDs are
generated, so do not compare against invented sample IDs. Additional fresh-key
declines add decisions/events; rejected authentication and invalid amounts do
not. Restarting the Java process without resetting PostgreSQL should preserve
the replay result; no in-memory cache is the source of truth.

Stop the Java process with Ctrl+C. Remove **only the disposable container you
created here** when finished:

```sh
docker stop atlaspay-java-walkthrough
```

This does not establish whole-system exactly-once delivery, production latency,
scale, or hosted-demo availability. The combined [HTTP contract](HTTP_CONTRACT.md)
documents validation and replay ordering, with both MVC tests and database-state
assertions. All flows remain simulations, not a payment provider integration.
