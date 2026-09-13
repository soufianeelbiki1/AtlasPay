# Java authorization HTTP boundary

This reference service simulates issuer authorization; it does not move real money.

POST /v1/authorizations requires internal bearer credentials and a nonblank
Idempotency-Key of at most 128 characters. Payment and issuer identifiers must
also be nonblank and at most 128 characters, matching PostgreSQL columns.
amountMinor must be positive. currency is required and must contain exactly
three uppercase letters. This is a shape check, not an ISO currency registry check.

Invalid input returns HTTP 400 before authorization or persistence. Missing
internal credentials returns HTTP 401. Identifiers are not silently normalized.

AuthorizationControllerTest exercises real Spring MVC validation and the internal
authentication filter with a mocked service. It checks valid delegation,
missing/null/malformed currency, blank/null/oversized identifiers, nonpositive
amounts, missing/blank/oversized keys and authentication. This is HTTP-layer
testing, not proof of database transactions by itself.

The combined AuthorizationHttpPostgresTest boots the real HTTP server and a
disposable PostgreSQL 16 container. Invalid currency/identifiers and oversized
keys return 400 with zero decisions/events. A corrected request may reuse the
rejected request's key. Validation still runs for invalid retries after a valid
decision exists: identical valid retries return the original response, changed
valid requests return 409, and both preserve one decision and one event. A
boundary case verifies 128-character keys/identifiers persist without truncation.

Run the MVC tests with Java 21 and Maven:

```bash
mvn -B -f java-service/pom.xml -Dtest=AuthorizationControllerTest test
```

No hosted account, external API or database credentials are needed for these MVC
tests. Production publishing still requires verified zero-cost eligibility.

For the combined HTTP/database and concurrency tests, Docker is also required:

```bash
mvn -B -f java-service/pom.xml -Dtest=AuthorizationControllerTest,AuthorizationHttpPostgresTest,AuthorizationPostgresTest test
```

See [the local walkthrough](LOCAL_WALKTHROUGH.md) for the complete simulated
authorization flow and its limits. These suites do not use hosted services.
