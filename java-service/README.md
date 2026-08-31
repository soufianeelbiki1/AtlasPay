# AtlasPay authorization service

This Java 21/Spring Boot 3 module owns a narrow authorization boundary beside the existing Python payment API. It persists decisions and an outbox event in one PostgreSQL transaction. Repeated Idempotency-Key values return the original decision; external delivery remains at-least-once and consumers must be idempotent.

Run locally with PostgreSQL and DATABASE_URL, then mvn spring-boot:run. GET /actuator/health is the readiness signal. Amounts above 1,000,000 minor units are deterministically declined for the simulation; this is not an issuer or card-network integration.