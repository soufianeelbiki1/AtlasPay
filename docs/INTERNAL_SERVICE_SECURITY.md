# Internal service security

The Java authorization and reconciliation endpoints are internal control-plane capabilities. They require a bearer token from the ATLASPAY_INTERNAL_TOKEN environment variable.

The filter:

- fails closed with HTTP 503 when the token is not configured;
- returns HTTP 401 for missing or invalid bearer credentials;
- compares tokens in constant time;
- leaves health, info and Prometheus endpoints available for platform probes;
- never exposes the internal token to Nexus or the browser.

The Java Railway service should not receive a public domain. AtlasPay-to-Java calls should use the private service address and the internal token. Token rotation should be performed by updating the Railway secret and redeploying both dependent services.

This is shared-secret service authentication for a portfolio deployment. It is not a claim of mTLS, zero-trust identity or production issuer security.
