import pytest

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.network_routing import (
    IssuerRoute,
    NetworkRouter,
    NetworkRoutingError,
    ReversalReason,
    ReversalRegistry,
)


def request(*, pan: str = "4111111111111111", currency: str = "MAD") -> AuthorizationRequest:
    return AuthorizationRequest(
        amount_minor=12_500,
        currency=currency,
        merchant_id="MERCHANT0000001",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(pan=pan),
        correlation=NetworkCorrelation(stan="123456", rrn="123456789012"),
    )


def test_router_prefers_longest_matching_pan_prefix() -> None:
    broad = IssuerRoute(
        name="visa-default",
        acquirer_id="acq-atlas",
        issuer_id="issuer-default",
        pan_prefix="4",
        currencies=frozenset({"MAD", "EUR"}),
    )
    specific = IssuerRoute(
        name="issuer-411111",
        acquirer_id="acq-atlas",
        issuer_id="issuer-bank-a",
        pan_prefix="411111",
        currencies=frozenset({"MAD"}),
    )

    assert NetworkRouter((broad, specific)).route(request()) == specific


def test_router_rejects_missing_currency_route() -> None:
    router = NetworkRouter(
        (
            IssuerRoute(
                name="mad-only",
                acquirer_id="acq-atlas",
                issuer_id="issuer-bank-a",
                pan_prefix="411111",
                currencies=frozenset({"MAD"}),
            ),
        )
    )

    with pytest.raises(NetworkRoutingError, match="no route"):
        router.route(request(currency="USD"))


def test_router_rejects_ambiguous_same_specificity_routes() -> None:
    router = NetworkRouter(
        (
            IssuerRoute(
                name="route-a",
                acquirer_id="acq-a",
                issuer_id="issuer-a",
                pan_prefix="411111",
                currencies=frozenset({"MAD"}),
            ),
            IssuerRoute(
                name="route-b",
                acquirer_id="acq-b",
                issuer_id="issuer-b",
                pan_prefix="411111",
                currencies=frozenset({"MAD"}),
            ),
        )
    )

    with pytest.raises(NetworkRoutingError, match="ambiguous issuer routing"):
        router.route(request())


def test_reversal_registry_links_original_and_reversal_once() -> None:
    original = NetworkCorrelation(stan="123456", rrn="123456789012")
    reversal = NetworkCorrelation(stan="654321", rrn="210987654321")
    registry = ReversalRegistry()

    link = registry.link(
        original=original,
        reversal=reversal,
        reason=ReversalReason.TIMEOUT,
    )

    assert registry.for_original(original) == link
    assert link.reason is ReversalReason.TIMEOUT

    with pytest.raises(ValueError, match="already has a reversal"):
        registry.link(
            original=original,
            reversal=NetworkCorrelation(stan="111111", rrn="111111111111"),
            reason=ReversalReason.OPERATOR,
        )


def test_reversal_correlation_cannot_be_reused() -> None:
    registry = ReversalRegistry()
    reversal = NetworkCorrelation(stan="654321", rrn="210987654321")
    registry.link(
        original=NetworkCorrelation(stan="123456", rrn="123456789012"),
        reversal=reversal,
        reason=ReversalReason.LATE_RESPONSE,
    )

    with pytest.raises(ValueError, match="already linked"):
        registry.link(
            original=NetworkCorrelation(stan="999999", rrn="999999999999"),
            reversal=reversal,
            reason=ReversalReason.TIMEOUT,
        )
