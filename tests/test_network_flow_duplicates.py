from dataclasses import dataclass

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.iso8583 import ISO8583Message
from app.network_coordinator import NetworkTransactionCoordinator, TransactionDisposition
from app.network_flow import AuthorizationNetworkFlow
from app.network_routing import IssuerRoute, NetworkRouter, ReversalRegistry
from app.network_transport import ISO8583NetworkAdapter, TransportExchange, TransportOutcome


@dataclass
class ScriptedTransport:
    result: TransportExchange

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange:
        assert payload
        return self.result


@dataclass
class ReversalCorrelation:
    value: NetworkCorrelation

    def next_for(self, *, original: NetworkCorrelation, route: IssuerRoute) -> NetworkCorrelation:
        return self.value


def test_late_response_is_deduplicated_after_timeout() -> None:
    correlation = NetworkCorrelation(stan="123456", rrn="123456789012")
    canonical = AuthorizationRequest(
        amount_minor=100,
        currency="MAD",
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(pan="4111111111111111"),
        correlation=correlation,
    )
    request = ISO8583Message("0200", {3: "000000", 11: "123456", 37: "123456789012"})
    response = ISO8583Message("0210", {11: "123456", 37: "123456789012", 39: "00"})
    route = IssuerRoute(
        name="issuer-a",
        acquirer_id="atlas-acquirer",
        issuer_id="issuer-bank-a",
        pan_prefix="411111",
        currencies=frozenset({"MAD"}),
    )
    flow = AuthorizationNetworkFlow(
        router=NetworkRouter((route,)),
        adapter=ISO8583NetworkAdapter(
            ScriptedTransport(TransportExchange(TransportOutcome.TIMEOUT, delivery_unknown=True))
        ),
        coordinator=NetworkTransactionCoordinator(),
        reversals=ReversalRegistry(),
        reversal_correlations=ReversalCorrelation(
            NetworkCorrelation(stan="654321", rrn="210987654321")
        ),
    )
    attempt = flow.start(canonical, request, now=0.0, timeout_seconds=1.0)

    timeout = flow.exchange(attempt, completed_at=1.0)
    first = flow.handle_late_response(attempt, response, now=1.5)
    second = flow.handle_late_response(attempt, response, now=1.6)

    assert timeout.disposition is TransactionDisposition.TIMED_OUT
    assert first is TransactionDisposition.LATE
    assert second is TransactionDisposition.DUPLICATE
