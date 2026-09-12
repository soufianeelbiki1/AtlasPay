package com.atlaspay;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/v1/authorizations")
class AuthorizationController {
  private final AuthorizationService service;

  AuthorizationController(AuthorizationService service) {
    this.service = service;
  }

  @PostMapping
  public ResponseEntity<AuthorizationResponse> authorize(
      @RequestHeader("Idempotency-Key") @NotBlank @Size(max = 128) String key,
      @Valid @RequestBody AuthorizationRequest request) {
    return ResponseEntity.ok(service.authorize(key, request));
  }

  record AuthorizationRequest(
      @NotBlank @Size(max = 128) String paymentId,
      @NotBlank @Size(max = 128) String issuerId,
      @Positive long amountMinor,
      @NotBlank @Pattern(regexp = "[A-Z]{3}") String currency) {}

  record AuthorizationResponse(UUID decisionId, String paymentId, String status, String reason) {}
}
