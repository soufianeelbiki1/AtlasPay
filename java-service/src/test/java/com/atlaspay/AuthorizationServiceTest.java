package com.atlaspay;

import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class AuthorizationServiceTest {
  @Test void amount_over_limit_is_declined_and_emits_outbox() {
    JdbcTemplate jdbc=mock(JdbcTemplate.class);
    when(jdbc.query(anyString(), any(), any())).thenReturn(java.util.List.of());
    AuthorizationService service=new AuthorizationService(jdbc);
    var response=service.authorize("idem-1", new AuthorizationController.AuthorizationRequest("pay-1","issuer-1",1_000_001,"EUR"));
    assertEquals("declined", response.status());
    verify(jdbc).update(contains("insert into outbox_events"), any(), any(), any(), any());
  }
}