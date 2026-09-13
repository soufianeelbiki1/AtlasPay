package com.atlaspay;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.HashMap;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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
    return authorize(key, Map.of("paymentId", "pay-local-1", "issuerId", "issuer-local-1",
        "amountMinor", amount, "currency", "EUR"), authenticated);
  }

  private ResponseEntity<JsonNode> authorize(
      String key, Map<String, Object> request, boolean authenticated) {
    var headers = new HttpHeaders();
    headers.set("Idempotency-Key", key);
    if (authenticated) headers.setBearerAuth(TOKEN);
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

  @ParameterizedTest
  @ValueSource(strings = {"missing-currency", "null-currency", "lowercase-currency",
      "blank-payment", "long-payment", "long-issuer"})
  void invalid_requests_neither_consume_a_key_nor_bypass_validation_on_replay(String variant) {
    var invalid = new HashMap<String, Object>(Map.of("paymentId", "pay-local-1",
        "issuerId", "issuer-local-1", "amountMinor", 1234, "currency", "EUR"));
    switch (variant) {
      case "missing-currency" -> invalid.remove("currency");
      case "null-currency" -> invalid.put("currency", null);
      case "lowercase-currency" -> invalid.put("currency", "eur");
      case "blank-payment" -> invalid.put("paymentId", "  ");
      case "long-payment" -> invalid.put("paymentId", "p".repeat(129));
      case "long-issuer" -> invalid.put("issuerId", "i".repeat(129));
      default -> throw new IllegalArgumentException(variant);
    }

    String key = "correctable-request";
    assertEquals(400, authorize(key, invalid, true).getStatusCode().value());
    assertCounts(0, 0);

    // A rejected request must not reserve the key. A corrected request can use it.
    var corrected = authorize(key, 1234, true);
    assertEquals(200, corrected.getStatusCode().value());
    assertNotNull(corrected.getBody());
    assertCounts(1, 1);

    // Validation must run even when a decision already exists for the key.
    assertEquals(400, authorize(key, invalid, true).getStatusCode().value());
    var replay = authorize(key, 1234, true);
    assertEquals(200, replay.getStatusCode().value());
    assertEquals(corrected.getBody(), replay.getBody());
    assertEquals(409, authorize(key, 1235, true).getStatusCode().value());
    assertCounts(1, 1);
    assertEquals(1234L, jdbc.queryForObject(
        "select amount_minor from authorization_decisions where idempotency_key=?",
        Long.class, key));
    assertEquals("EUR", jdbc.queryForObject(
        "select currency from authorization_decisions where idempotency_key=?", String.class, key));
  }

  @Test
  void oversized_http_key_is_rejected_without_database_writes() {
    assertEquals(400, authorize("k".repeat(129), 1234, true).getStatusCode().value());
    assertCounts(0, 0);
  }

  @Test
  void maximum_length_identifiers_are_persisted_exactly_and_replay_safely() {
    String key = "k".repeat(128);
    var request = Map.<String, Object>of("paymentId", "p".repeat(128),
        "issuerId", "i".repeat(128), "amountMinor", 1234, "currency", "EUR");
    var first = authorize(key, request, true);
    var replay = authorize(key, request, true);
    assertEquals(200, first.getStatusCode().value());
    assertEquals(200, replay.getStatusCode().value());
    assertNotNull(first.getBody());
    assertEquals(first.getBody(), replay.getBody());
    assertCounts(1, 1);
    assertEquals(request.get("paymentId"), jdbc.queryForObject(
        "select payment_id from authorization_decisions where idempotency_key=?", String.class, key));
    assertEquals(request.get("issuerId"), jdbc.queryForObject(
        "select issuer_id from authorization_decisions where idempotency_key=?", String.class, key));
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
