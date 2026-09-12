package com.atlaspay;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.junit.jupiter.api.Assertions.*;

@Testcontainers
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Timeout(60)
class AuthorizationHttpPostgresTest {
  private static final String TOKEN = "local-http-test-token-not-a-secret";

  @Container
  static final PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine");

  @DynamicPropertySource
  static void properties(DynamicPropertyRegistry registry) {
    registry.add("spring.datasource.url", postgres::getJdbcUrl);
    registry.add("spring.datasource.username", postgres::getUsername);
    registry.add("spring.datasource.password", postgres::getPassword);
    registry.add("ATLASPAY_INTERNAL_TOKEN", () -> TOKEN);
  }

  @Autowired TestRestTemplate http;
  @Autowired JdbcTemplate jdbc;

  @BeforeEach
  void reset() {
    // Only the outbox columns written by this boundary are required here.
    // This does not start an outbox publisher or the Python payment stack.
    jdbc.execute("create table if not exists outbox_events (id text primary key, aggregate_type text not null, aggregate_id text not null, event_type text not null, payload jsonb not null)");
    jdbc.execute("truncate authorization_decisions, outbox_events");
  }

  private ResponseEntity<JsonNode> authorize(String key, long amount, boolean authenticated) {
    var headers = new HttpHeaders();
    headers.set("Idempotency-Key", key);
    if (authenticated) headers.setBearerAuth(TOKEN);
    var request = Map.of("paymentId", "pay-local-1", "issuerId", "issuer-local-1",
        "amountMinor", amount, "currency", "EUR");
    return http.exchange("/v1/authorizations", HttpMethod.POST,
        new HttpEntity<>(request, headers), JsonNode.class);
  }

  private void assertCounts(int decisions, int events) {
    assertEquals(decisions, jdbc.queryForObject("select count(*) from authorization_decisions", Integer.class));
    assertEquals(events, jdbc.queryForObject("select count(*) from outbox_events", Integer.class));
  }

  @Test
  void identical_http_retry_and_changed_request_preserve_the_original_decision() {
    var first = authorize("http-replay", 1234, true);
    var retry = authorize("http-replay", 1234, true);
    assertEquals(200, first.getStatusCode().value());
    assertEquals(200, retry.getStatusCode().value());
    assertNotNull(first.getBody());
    assertEquals(first.getBody(), retry.getBody());
    assertEquals("approved", first.getBody().path("status").asText());
    assertFalse(first.getBody().path("decisionId").asText().isBlank());

    assertEquals(409, authorize("http-replay", 1235, true).getStatusCode().value());
    assertCounts(1, 1);
    assertEquals(1234L, jdbc.queryForObject("select amount_minor from authorization_decisions where idempotency_key='http-replay'", Long.class));
    assertEquals(first.getBody().path("decisionId").asText(),
        jdbc.queryForObject("select decision_id::text from authorization_decisions where idempotency_key='http-replay'", String.class));
    assertEquals("approved", jdbc.queryForObject("select payload->>'status' from outbox_events", String.class));
  }

  @Test
  void missing_http_credentials_never_write_a_decision_or_event() {
    assertEquals(401, authorize("http-no-auth", 1234, false).getStatusCode().value());
    assertCounts(0, 0);
  }

  @Test
  void invalid_http_amount_never_writes_a_decision_or_event() {
    assertEquals(400, authorize("http-invalid", 0, true).getStatusCode().value());
    assertCounts(0, 0);
  }

  @Test
  void simulated_decline_is_a_persisted_decision_not_an_http_transport_error() {
    var response = authorize("http-decline", 1_000_001, true);
    assertEquals(200, response.getStatusCode().value());
    assertNotNull(response.getBody());
    assertEquals("declined", response.getBody().path("status").asText());
    assertEquals("amount_limit", response.getBody().path("reason").asText());
    assertCounts(1, 1);
    assertEquals("declined", jdbc.queryForObject("select payload->>'status' from outbox_events", String.class));
  }
}
