package com.atlaspay;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.UUID;

@Service
class AuthorizationService {
  private final JdbcTemplate jdbc;
  private final ObjectMapper objectMapper;

  AuthorizationService(JdbcTemplate jdbc, ObjectMapper objectMapper) {
    this.jdbc = jdbc;
    this.objectMapper = objectMapper;
  }

  @Transactional
  public AuthorizationController.AuthorizationResponse authorize(
      String key, AuthorizationController.AuthorizationRequest request) {
    var existing = jdbc.query(
        "select decision_id,payment_id,status,reason from authorization_decisions where idempotency_key=?",
        ps -> ps.setString(1, key),
        (rs, n) -> new AuthorizationController.AuthorizationResponse(
            UUID.fromString(rs.getString(1)),
            rs.getString(2),
            rs.getString(3),
            rs.getString(4)));

    if (!existing.isEmpty()) {
      return existing.getFirst();
    }

    String status = request.amountMinor() > 1_000_000 ? "declined" : "approved";
    String reason = status.equals("approved") ? "issuer_approved" : "amount_limit";
    UUID decisionId = UUID.randomUUID();

    jdbc.update(
        "insert into authorization_decisions(decision_id,idempotency_key,payment_id,issuer_id,amount_minor,currency,status,reason) values (?,?,?,?,?,?,?,?)",
        decisionId,
        key,
        request.paymentId(),
        request.issuerId(),
        request.amountMinor(),
        request.currency(),
        status,
        reason);

    jdbc.update(
        "insert into outbox_events(id,aggregate_type,aggregate_id,event_type,payload) values (?,?,?,?,?::jsonb)",
        UUID.randomUUID().toString(),
        "payment",
        request.paymentId(),
        "authorization.decided",
        authorizationPayload(status));

    return new AuthorizationController.AuthorizationResponse(
        decisionId, request.paymentId(), status, reason);
  }

  private String authorizationPayload(String status) {
    try {
      return objectMapper.writeValueAsString(Map.of("status", status));
    } catch (JsonProcessingException exception) {
      throw new IllegalStateException("Could not serialize authorization event", exception);
    }
  }
}
