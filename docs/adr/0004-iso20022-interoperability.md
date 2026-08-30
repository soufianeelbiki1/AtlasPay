# ADR 0004: ISO 8583 / canonical / ISO 20022 interoperability boundary

## Status

Accepted for the current AtlasPay reference implementation.

## Context

AtlasPay already maps a deliberately narrow ISO 8583 purchase-authorization
profile through a protocol-independent canonical model. ISO 20022 card-payment
messages are richer and versioned; claiming broad ISO 20022 conformance without
an exact message family, XSD version, transport profile, and certification
evidence would be misleading.

## Decision

AtlasPay introduces a schema-neutral ISO20022CardAuthorization projection for
the concepts the current canonical authorization can represent: message and
transaction identity, amount/currency, merchant/terminal identity, and card PAN.

Concrete ISO 20022 XML card-message parsing, schema validation, namespaces,
version negotiation, and network transport remain outside this projection and
require their own adapter.

All conversions continue through AuthorizationRequest; ISO 8583 and ISO 20022
types do not map directly to one another.

### Mapping table

| Canonical concept | ISO 8583 profile | ISO 20022 projection | Semantics |
| --- | --- | --- | --- |
| amount minor units | DE4, 12 numeric digits | amount_minor | Lossless within DE4 width |
| currency | DE49 numeric | currency alpha code | Lossless only for configured currency dictionary |
| PAN | DE2 | pan | Represented; production systems should tokenize/protect |
| merchant id | DE42 | merchant_id | ISO 8583 return path additionally requires exact DE42 width |
| terminal id | DE41 | terminal_id | ISO 8583 return path additionally requires exact DE41 width |
| RRN | DE37 | transaction_id | Current bridge requires 12 printable characters |
| STAN | DE11 | not projected | Explicit loss; network-specific trace is allocated on ISO 8583 boundary |
| ICC / EMV data | DE55 | not projected | Explicit loss until a concrete ISO 20022 card-message adapter maps supported EMV elements |

## Failure boundaries

- Unsupported ISO 8583 processing codes or currencies fail closed.
- ISO 20022 transaction identifiers that cannot fit the current RRN correlation
  profile fail closed on the ISO 8583-facing bridge.
- DE55 is never silently copied into an invented ISO 20022 field. The projection
  returns an explicit loss record.
- No XML/XSD conformance, card-scheme certification, or network interoperability
  claim follows from this internal projection.

## Consequences

The canonical model remains the interoperability pivot and protocol concerns do
not leak into ledger or transport code. The cost is that the current bridge is
intentionally narrower than ISO 20022 itself. A later XML adapter must choose a
specific message family/version and document every additional mapping.
