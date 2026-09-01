package com.atlaspay;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
class InternalServiceAuthFilter extends OncePerRequestFilter {
  private static final Set<String> PROTECTED_PREFIXES =
      Set.of("/v1/authorizations", "/reconciliation");

  private final Environment environment;

  InternalServiceAuthFilter(Environment environment) {
    this.environment = environment;
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request,
      HttpServletResponse response,
      FilterChain filterChain)
      throws ServletException, java.io.IOException {
    if (!isProtectedPath(request.getRequestURI())) {
      filterChain.doFilter(request, response);
      return;
    }

    String expected = environment.getProperty("ATLASPAY_INTERNAL_TOKEN", "");
    if (expected.isBlank()) {
      writeError(response, HttpServletResponse.SC_SERVICE_UNAVAILABLE,
          "Internal service authentication is not configured");
      return;
    }

    String supplied = bearerToken(request.getHeader("Authorization"));
    if (supplied == null || !constantTimeEquals(supplied, expected)) {
      response.setHeader("WWW-Authenticate", "Bearer");
      writeError(response, HttpServletResponse.SC_UNAUTHORIZED,
          "Valid internal bearer credentials are required");
      return;
    }

    filterChain.doFilter(request, response);
  }

  private static boolean isProtectedPath(String path) {
    return PROTECTED_PREFIXES.stream().anyMatch(path::startsWith);
  }

  private static String bearerToken(String header) {
    if (header == null) {
      return null;
    }
    int separator = header.indexOf(' ');
    if (separator <= 0 || !"bearer".equalsIgnoreCase(header.substring(0, separator))) {
      return null;
    }
    String token = header.substring(separator + 1).trim();
    return token.isEmpty() ? null : token;
  }

  private static boolean constantTimeEquals(String supplied, String expected) {
    return MessageDigest.isEqual(
        supplied.getBytes(StandardCharsets.UTF_8),
        expected.getBytes(StandardCharsets.UTF_8));
  }

  private static void writeError(
      HttpServletResponse response, int status, String detail)
      throws java.io.IOException {
    response.setStatus(status);
    response.setContentType("application/json");
    response.getWriter().write("{\"detail\":\"" + detail + "\"}");
  }
}
