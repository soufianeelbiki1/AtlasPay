"""Transport-independent issuer/acquirer routing and reversal linkage.

Routing works on the canonical payment model. Reversal linkage tracks business
correlation without pretending that transport delivery is exactly once.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.canonical import AuthorizationRequest, NetworkCorrelation


class NetworkRoutingError(ValueError):
    """Raised when a request cannot be routed unambiguously."""


@dataclass(frozen=True, slots=True)
class IssuerRoute:
    name: str
    acquirer_id: str
    issuer_id: str
    pan_prefix: str
    currencies: frozenset[str]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("route name must not be empty")
        if not self.acquirer_id.strip() or not self.issuer_id.strip():
            raise ValueError("acquirer_id and issuer_id must not be empty")
        if not self.pan_prefix.isdigit():
            raise ValueError("pan_prefix must contain only digits")
        if not self.currencies:
            raise ValueError("route must support at least one currency")
        if any(currency != currency.upper() for currency in self.currencies):
            raise ValueError("route currencies must use uppercase ISO alpha codes")


class NetworkRouter:
    """Selects the most-specific eligible route for a canonical authorization."""

    def __init__(self, routes: tuple[IssuerRoute, ...]) -> None:
        if not routes:
            raise ValueError("at least one issuer route is required")
        self._routes = routes

    def route(self, request: AuthorizationRequest) -> IssuerRoute:
        matches = [
            route
            for route in self._routes
            if request.instrument.pan.startswith(route.pan_prefix)
            and request.currency in route.currencies
        ]
        if not matches:
            raise NetworkRoutingError(
                f"no route for PAN prefix/currency combination ({request.currency})"
            )

        longest_prefix = max(len(route.pan_prefix) for route in matches)
        most_specific = [
            route for route in matches if len(route.pan_prefix) == longest_prefix
        ]
        if len(most_specific) != 1:
            names = ", ".join(sorted(route.name for route in most_specific))
            raise NetworkRoutingError(f"ambiguous issuer routing between: {names}")
        return most_specific[0]


class ReversalReason(StrEnum):
    TIMEOUT = "timeout"
    LATE_RESPONSE = "late_response"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class ReversalLink:
    original: NetworkCorrelation
    reversal: NetworkCorrelation
    reason: ReversalReason


class ReversalRegistry:
    """Tracks a single reversal correlation for each original network transaction.

    This is correlation state only. It does not claim the reversal was delivered or
    accepted by an external issuer; those outcomes belong to the network coordinator.
    """

    def __init__(self) -> None:
        self._by_original: dict[NetworkCorrelation, ReversalLink] = {}
        self._reversal_keys: set[NetworkCorrelation] = set()

    def link(
        self,
        *,
        original: NetworkCorrelation,
        reversal: NetworkCorrelation,
        reason: ReversalReason,
    ) -> ReversalLink:
        if original == reversal:
            raise ValueError("reversal correlation must differ from the original")
        if original in self._by_original:
            raise ValueError("original transaction already has a reversal")
        if reversal in self._reversal_keys:
            raise ValueError("reversal correlation is already linked")

        link = ReversalLink(original=original, reversal=reversal, reason=reason)
        self._by_original[original] = link
        self._reversal_keys.add(reversal)
        return link

    def for_original(self, original: NetworkCorrelation) -> ReversalLink | None:
        return self._by_original.get(original)
