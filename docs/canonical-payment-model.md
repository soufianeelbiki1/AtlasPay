# Canonical payment boundary

AtlasPay keeps payment-domain behavior separate from payment-network wire formats.

```text
ISO 8583 bytes
    |
    v
ISO8583Codec
    |
    v
ISO8583Message
    |
    v
ISO 8583 adapter
    |
    v
AuthorizationRequest (canonical)
    |
    +--> routing / risk / ledger / events
    |
    v
network-specific adapter
```

## Why a canonical model

Routing, ledger, risk, event, and reconciliation code should not need to know that an upstream network stores an amount in DE4, a currency in DE49, or correlation references in DE11/DE37. The adapter owns those protocol details and either produces a valid canonical request or rejects the mapping explicitly.

This boundary also creates the intended interoperability point for future ISO 20022 support:

```text
ISO 8583 <-> canonical model <-> ISO 20022
```

Mappings are deliberately explicit. AtlasPay does not silently invent values when a source protocol cannot represent a required canonical field.

## Current authorization mapping

The first adapter slice supports ISO 8583 MTI `0200` purchase authorizations using processing code `000000`.

| ISO 8583 element | Canonical field | Notes |
| --- | --- | --- |
| DE2 | `instrument.pan` | Simulation only; production systems should tokenize PAN data and apply PCI DSS controls. |
| DE3 | purchase operation | Only `000000` is currently accepted. |
| DE4 | `amount_minor` | Parsed as a positive integer in minor units. |
| DE11 | `correlation.stan` | Six-digit switch trace reference. |
| DE37 | `correlation.rrn` | Twelve-character retrieval reference. |
| DE41 | `terminal_id` | ISO adapter enforces the current eight-character profile on encoding. |
| DE42 | `merchant_id` | ISO adapter enforces the current fifteen-character profile on encoding. |
| DE49 | `currency` | Explicit numeric-to-alpha mapping; currently MAD (504), USD (840), EUR (978). |
| DE55 | `instrument.icc_data` | Optional binary ICC/EMV payload; semantic TLV parsing is a later slice. |

## Correlation contract

A response is correlated only when both conditions hold:

1. the response MTI is the expected response for the request MTI; and
2. the DE11 STAN and DE37 RRN pair matches the original request.

For example, a `0200` request expects a `0210` response. Matching a STAN alone is intentionally insufficient because STAN values are short and routinely reused over time.

Timeout storage, late-response classification, duplicate windows, and reversal linkage will build on this correlation key in later slices.

## Failure behavior

The adapter fails closed when:

- the MTI is not supported;
- a required data element is missing;
- a required text element has the wrong runtime type;
- the processing code is not mapped;
- the currency is not mapped;
- the amount is zero or negative; or
- a canonical value cannot fit the configured ISO 8583 field width.

This is intentional. Network-specific fallback behavior belongs in an explicit network profile rather than in the canonical model.
