from dataclasses import dataclass

import pytest

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.iso8583 import ISO8583Codec, ISO8583Message
from app.network_coordinator import NetworkTransactionCoordinator, TransactionDisposition
from app.network_flow import AuthorizationNetworkFlow
from app.network_routing import IssuerRoute, NetworkRouter, ReversalRegistry
from app.network_transport import (
    ISO8583NetworkAdapter,
    TransportExchange,
    TransportOutcome,
)


@dataclass
class ScriptedTransport:
    result: TransportExchange

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange:
        assert payload
        assert timeout_seconds > 0
        return self.result


@dataclass
class StaticReversalCorrelations:
    value: NetworkCorrelation

    def next_for(
        self,
        *,
        original: NetworkCorrelation,
        route: IssuerRoute,
    ) -> NetworkCorrelation:
        assert route.issuer_id == "issuer-bank-a"
        assert original != self.value
        return self.value


def canonical() -> AuthorizationRequest:
    return AuthorizationRequest(
        amount_minor=12_500,
        currency="MAD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(pan="4111111111111111"),
        correlation=NetworkCorrelation(stan="123456", rrn="123456789012"),
    )


def request() -> ISO8583Message:
    return ISO8583Message(
        "0200",
        {
            3: "000000",
            11: "123456",
            37: "123456789012",
        },
    )


def response() -> ISO8583Message:
    return ISO8583Message(
        "0210",
        {
            11: "123456",
            37: "123456789012",
            39: "00",
        },
    )


def route() -> IssuerRoute:
    return IssuerRoute(
        name="issuer-a",
        acquirer_id="atlas-acquirer",
        issuer_id="issuer-bank-a",
        pan_prefix="411111",
        currencies=frozenset({"MAD"}),
    )


def flow(exchange: TransportExchange) -> tuple[AuthorizationNetworkFlow, ReversalRegistry]:
    reversals = ReversalRegistry()
    return (
        AuthorizationNetworkFlow(
            router=NetworkRouter((route(),)),
            adapter=ISO8583NetworkAdapter(ScriptedTransport(exchange)),
            coordinator=NetworkTransactionCoordinator(),
            reversals=reversals,
            reversal_correlations=StaticReversalCorrelations(
                NetworkCorrelation(stan="654321", rrn="210987654321")
            ),
        ),
        reversals,
    )


def test_timeout_creates_reversal_link_without_delivery_claim() -> None:
    service, reversals = flow(
        TransportExchange(
            TransportOutcome.TIMEOUT,
            error="issuer response deadline exceeded",
            delivery_unknown=True,
        )
    )
    attempt = service.start(canonical(), request(), now=10.0, timeout_seconds=5.0)

    result = service.exchange(attempt, completed_at=15.0)

    assert result.disposition is TransactionDisposition.TIMED_OUT
    assert result.delivery_unknown is True
    assert result.reversal is not None
    assert result.reversal.original == canonical().correlation
    assert reversals.for_original(canonical().correlation) == result.reversal


def test_late_original_response_after_timeout_and_reversal_is_explicit() -> None:
    service, _ = flow(
        TransportExchange(
            TransportOutcome.TIMEOUT,
            delivery_unknown=True,
        )
    )
    attempt = service.start(canonical(), request(), now=0.0, timeout_seconds=2.0)
    timed_out = service.exchange(attempt, completed_at=2.0)

    disposition = service.handle_late_response(attempt, response(), now=2.5)

    assert timed_out.reversal is not None
    assert disposition is TransactionDisposition.LATE


def test_accepted_response_completes_without_reversal() -> None:
    codec = ISO8583Codec()
    service, reversals = flow(
        TransportExchange(
            TransportOutcome.RESPONSE,
            response_payload=codec.encode(response()),
        )
    )
    attempt = service.start(canonical(), request(), now=1.0, timeout_seconds=5.0)

    result = service.exchange(attempt, completed_at=2.0)

    assert result.disposition is TransactionDisposition.ACCEPTED
    assert result.reversal is None
    assert reversals.for_original(canonical().correlation) is None


def test_response_received_at_deadline_is_classified_late() -> None:
    codec = ISO8583Codec()
    service, _ = flow(
        TransportExchange(
            TransportOutcome.RESPONSE,
            response_payload=codec.encode(response()),
        )
    )
    attempt = service.start(canonical(), request(), now=1.0, timeout_seconds=5.0)

    result = service.exchange(attempt, completed_at=6.0)

    assert result.disposition is TransactionDisposition.LATE


def test_known_local_transport_failure_cancels_pending_for_safe_retry() -> None:
    service, _ = flow(
        TransportExchange(
            TransportOutcome.FAILURE,
            error="connection refused before write",
        )
    )
    attempt = service.start(canonical(), request(), now=0.0, timeout_seconds=5.0)

    result = service.exchange(attempt, completed_at=0.1)
    retry = service.start(canonical(), request(), now=0.2, timeout_seconds=5.0)

    assert result.transport_outcome is TransportOutcome.FAILURE
    assert result.delivery_unknown is False
    assert retry.correlation == attempt.correlation


def test_start_rejects_canonical_wire_correlation_mismatch() -> None:
    service, _ = flow(TransportExchange(TransportOutcome.FAILURE, error="unused"))
    mismatched = ISO8583Message(
        "0200",
        {
            3: "000000",
            11: "999999",
            37: "999999999999",
        },
    )

    with pytest.raises(ValueError, match="correlation must match"):
        service.start(canonical(), mismatched, now=0.0, timeout_seconds=5.0)


def test_timeout_before_registered_deadline_is_rejected() -> None:
    service, _ = flow(
        TransportExchange(
            TransportOutcome.TIMEOUT,
            delivery_unknown=True,
        )
    )
    attempt = service.start(canonical(), request(), now=0.0, timeout_seconds=5.0)

    with pytest.raises(ValueError, match="before the registered deadline"):
        service.exchange(attempt, completed_at=4.9)
