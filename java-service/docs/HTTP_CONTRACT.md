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
testing, not proof of database transactions; replay/concurrency work is separate.

Run the MVC tests with Java 21 and Maven:

```bash
mvn -B -f java-service/pom.xml -Dtest=AuthorizationControllerTest test
```

No hosted account, external API or database credentials are needed for these MVC
tests. Production publishing still requires verified zero-cost eligibility.
