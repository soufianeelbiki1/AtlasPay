package com.atlaspay;

import java.util.Map;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(AuthorizationController.class)
@TestPropertySource(properties = "ATLASPAY_INTERNAL_TOKEN=test-internal-token")
class AuthorizationControllerTest {
  @Autowired MockMvc mvc;
  @Autowired ObjectMapper mapper;
  @MockBean AuthorizationService service;

  private Map<String, Object> validBody() {
    return new java.util.HashMap<>(Map.of(
        "paymentId", "pay-1", "issuerId", "issuer-1", "amountMinor", 100, "currency", "EUR"));
  }

  @Test
  void valid_authenticated_request_reaches_the_service() throws Exception {
    var id = UUID.randomUUID();
    when(service.authorize(eq("key-1"), any())).thenReturn(
        new AuthorizationController.AuthorizationResponse(id, "pay-1", "approved", "issuer_approved"));
    mvc.perform(post("/v1/authorizations")
        .header("Authorization", "Bearer test-internal-token").header("Idempotency-Key", "key-1")
        .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(validBody())))
        .andExpect(status().isOk()).andExpect(jsonPath("$.decisionId").value(id.toString()));
    verify(service).authorize("key-1", new AuthorizationController.AuthorizationRequest(
        "pay-1", "issuer-1", 100, "EUR"));
  }

  @ParameterizedTest
  @ValueSource(strings = {"missing-currency", "null-currency", "lowercase-currency",
      "blank-payment", "null-issuer", "long-payment", "long-issuer", "zero-amount", "negative-amount"})
  void invalid_body_returns_bad_request_without_service_calls(String variant) throws Exception {
    var body = validBody();
    switch (variant) {
      case "missing-currency" -> body.remove("currency");
      case "null-currency" -> body.put("currency", null);
      case "lowercase-currency" -> body.put("currency", "eur");
      case "blank-payment" -> body.put("paymentId", "  ");
      case "null-issuer" -> body.put("issuerId", null);
      case "long-payment" -> body.put("paymentId", "p".repeat(129));
      case "long-issuer" -> body.put("issuerId", "i".repeat(129));
      case "zero-amount" -> body.put("amountMinor", 0);
      case "negative-amount" -> body.put("amountMinor", -1);
      default -> throw new IllegalArgumentException(variant);
    }
    mvc.perform(post("/v1/authorizations")
        .header("Authorization", "Bearer test-internal-token").header("Idempotency-Key", "key-1")
        .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(body)))
        .andExpect(status().isBadRequest());
    verifyNoInteractions(service);
  }

  @ParameterizedTest
  @ValueSource(strings = {"missing", "blank", "oversized"})
  void invalid_key_returns_bad_request_without_service_calls(String variant) throws Exception {
    var request = post("/v1/authorizations")
        .header("Authorization", "Bearer test-internal-token")
        .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(validBody()));
    if (!variant.equals("missing")) {
      request.header("Idempotency-Key", variant.equals("blank") ? "  " : "k".repeat(129));
    }
    mvc.perform(request).andExpect(status().isBadRequest());
    verifyNoInteractions(service);
  }

  @Test
  void missing_internal_credentials_returns_unauthorized() throws Exception {
    mvc.perform(post("/v1/authorizations").header("Idempotency-Key", "key-1")
        .contentType(MediaType.APPLICATION_JSON).content(mapper.writeValueAsString(validBody())))
        .andExpect(status().isUnauthorized());
    verifyNoInteractions(service);
  }
}
