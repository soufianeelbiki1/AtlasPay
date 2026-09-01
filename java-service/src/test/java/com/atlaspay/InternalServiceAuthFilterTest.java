package com.atlaspay;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class InternalServiceAuthFilterTest {
  @Test
  void protected_endpoint_requires_configured_token() throws Exception {
    var filter = new InternalServiceAuthFilter(new MockEnvironment());
    var request = new MockHttpServletRequest("POST", "/v1/authorizations");
    var response = new MockHttpServletResponse();
    var chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertEquals(503, response.getStatus());
    assertNull(chain.getRequest());
  }

  @Test
  void protected_endpoint_rejects_invalid_token() throws Exception {
    var environment = new MockEnvironment()
        .withProperty("ATLASPAY_INTERNAL_TOKEN", "expected-token");
    var filter = new InternalServiceAuthFilter(environment);
    var request = new MockHttpServletRequest("POST", "/reconciliation/runs");
    request.addHeader("Authorization", "Bearer wrong-token");
    var response = new MockHttpServletResponse();
    var chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertEquals(401, response.getStatus());
    assertEquals("Bearer", response.getHeader("WWW-Authenticate"));
    assertNull(chain.getRequest());
  }

  @Test
  void valid_token_reaches_protected_endpoint() throws Exception {
    var environment = new MockEnvironment()
        .withProperty("ATLASPAY_INTERNAL_TOKEN", "expected-token");
    var filter = new InternalServiceAuthFilter(environment);
    var request = new MockHttpServletRequest("POST", "/v1/authorizations");
    request.addHeader("Authorization", "Bearer expected-token");
    var response = new MockHttpServletResponse();
    var chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertEquals("/v1/authorizations", chain.getRequest().getRequestURI());
  }

  @Test
  void health_endpoint_remains_public() throws Exception {
    var filter = new InternalServiceAuthFilter(new MockEnvironment());
    var request = new MockHttpServletRequest("GET", "/actuator/health");
    var response = new MockHttpServletResponse();
    var chain = new MockFilterChain();

    filter.doFilter(request, response, chain);

    assertEquals(200, response.getStatus());
    assertEquals("/actuator/health", chain.getRequest().getRequestURI());
  }
}
