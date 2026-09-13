package com.atlaspay;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.PreparedStatementSetter;
import org.springframework.jdbc.core.RowMapper;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AuthorizationServiceTest {
  @Test
  void identical_retry_returns_original_decision_without_writing() {
    JdbcTemplate jdbc = mock(JdbcTemplate.class);
    var request = new AuthorizationController.AuthorizationRequest("pay-1", "issuer-1", 100, "EUR");
    var response = new AuthorizationController.AuthorizationResponse(
        java.util.UUID.randomUUID(), "pay-1", "approved", "issuer_approved");
    when(jdbc.query(anyString(), any(PreparedStatementSetter.class), any(RowMapper.class)))
        .thenReturn(java.util.List.of(new AuthorizationService.StoredDecision(response, request)));

    var service = new AuthorizationService(jdbc, new com.fasterxml.jackson.databind.ObjectMapper());
    assertEquals(response, service.authorize("idem-1", request));
    verify(jdbc, never()).update(anyString(), any(Object[].class));
  }

  @Test
  void changed_request_fields_conflict_without_writing() {
    var original = new AuthorizationController.AuthorizationRequest("pay-1", "issuer-1", 100, "EUR");
    var variants = java.util.List.of(
        new AuthorizationController.AuthorizationRequest("pay-2", "issuer-1", 100, "EUR"),
        new AuthorizationController.AuthorizationRequest("pay-1", "issuer-2", 100, "EUR"),
        new AuthorizationController.AuthorizationRequest("pay-1", "issuer-1", 101, "EUR"),
        new AuthorizationController.AuthorizationRequest("pay-1", "issuer-1", 100, "USD"));
    for (var changed : variants) {
      JdbcTemplate jdbc = mock(JdbcTemplate.class);
      var response = new AuthorizationController.AuthorizationResponse(
          java.util.UUID.randomUUID(), "pay-1", "approved", "issuer_approved");
      when(jdbc.query(anyString(), any(PreparedStatementSetter.class), any(RowMapper.class)))
          .thenReturn(java.util.List.of(new AuthorizationService.StoredDecision(response, original)));
      var service = new AuthorizationService(jdbc, new com.fasterxml.jackson.databind.ObjectMapper());
      var exception = assertThrows(org.springframework.web.server.ResponseStatusException.class,
          () -> service.authorize("idem-1", changed));
      assertEquals(org.springframework.http.HttpStatus.CONFLICT, exception.getStatusCode());
      verify(jdbc, never()).update(anyString(), any(Object[].class));
    }
  }

  @Test
  void amount_over_limit_is_declined_and_emits_shared_outbox_event() {
    JdbcTemplate jdbc = mock(JdbcTemplate.class);
    when(jdbc.update(contains("insert into authorization_decisions"), any(Object[].class)))
        .thenReturn(1);
    when(jdbc.query(anyString(), any(PreparedStatementSetter.class), any(RowMapper.class)))
        .thenReturn(java.util.List.of());

    AuthorizationService service = new AuthorizationService(jdbc, new com.fasterxml.jackson.databind.ObjectMapper());
    var response = service.authorize(
        "idem-1",
        new AuthorizationController.AuthorizationRequest(
            "pay-1", "issuer-1", 1_000_001, "EUR"));

    assertEquals("declined", response.status());
    verify(jdbc).update(
        contains("insert into outbox_events"),
        anyString(),
        eq("payment"),
        eq("pay-1"),
        eq("authorization.decided"),
        eq("{\"status\":\"declined\"}"));
  }
}
