"""Issuer network lifecycle orchestration across routing, transport, and reversals."""

from dataclasses import dataclass
from typing import Protocol

from app.canonical import AuthorizationRequest, NetworkCorrelation
from app.iso8583 import ISO8583Message
from app.iso8583_adapter import correlation_key
from app.network_coordinator import NetworkTransactionCoordinator, TransactionDisposition
from app.network_observability import NetworkTelemetry
from app.network_routing import (
    IssuerRoute,
    NetworkRouter,
    ReversalLink,
    ReversalReason,
    ReversalRegistry,
)
from app.network_transport import ISO8583NetworkAdapter, TransportOutcome


class ReversalCorrelationProvider(Protocol):
    """Provide a fresh reversal correlation without implying network delivery."""

    def next_for(
        self,
        *,
        original: NetworkCorrelation,
        route: IssuerRoute,
    ) -> NetworkCorrelation: ...


@dataclass(frozen=True, slots=True)
class NetworkAttempt:
    route: IssuerRoute
    request: ISO8583Message
    correlation: NetworkCorrelation
    started_at: float
    deadline: float
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class NetworkFlowResult:
    route: IssuerRoute
    transport_outcome: TransportOutcome
    disposition: TransactionDisposition | None
    delivery_unknown: bool
    reversal: ReversalLink | None = None
    error: str | None = None


class AuthorizationNetworkFlow:
    """Coordinate one authorization attempt without collapsing failure boundaries."""

    def __init__(
        self,
        *,
        router: NetworkRouter,
        adapter: ISO8583NetworkAdapter,
        coordinator: NetworkTransactionCoordinator,
        reversals: ReversalRegistry,
        reversal_correlations: ReversalCorrelationProvider,
        telemetry: NetworkTelemetry | None = None,
    ) -> None:
        self._router = router
        self._adapter = adapter
        self._coordinator = coordinator
        self._reversals = reversals
        self._reversal_correlations = reversal_correlations
        self._telemetry = telemetry

    def start(
        self,
        canonical: AuthorizationRequest,
        request: ISO8583Message,
        *,
        now: float,
        timeout_seconds: float,
    ) -> NetworkAttempt:
        wire_correlation = correlation_key(request)
        if wire_correlation != canonical.correlation:
            raise ValueError("canonical and ISO 8583 correlation must match")

        route = self._router.route(canonical)
        correlation = self._coordinator.register(
            request,
            now=now,
            timeout=timeout_seconds,
        )
        return NetworkAttempt(
            route=route,
            request=request,
            correlation=correlation,
            started_at=now,
            deadline=now + timeout_seconds,
            timeout_seconds=timeout_seconds,
        )

    def exchange(
        self,
        attempt: NetworkAttempt,
        *,
        completed_at: float,
    ) -> NetworkFlowResult:
        if self._telemetry is None:
            return self._exchange(attempt, completed_at=completed_at)

        with self._telemetry.observe_exchange(attempt.route) as observation:
            result = self._exchange(attempt, completed_at=completed_at)
            observation.transport_outcome = result.transport_outcome
            observation.disposition = result.disposition
            observation.delivery_unknown = result.delivery_unknown
            if result.reversal is not None:
                observation.reversal_reason = result.reversal.reason
            return result

    def _exchange(
        self,
        attempt: NetworkAttempt,
        *,
        completed_at: float,
    ) -> NetworkFlowResult:
        result = self._adapter.exchange(
            attempt.request,
            timeout_seconds=attempt.timeout_seconds,
        )

        if result.outcome is TransportOutcome.FAILURE:
            cancelled = self._coordinator.cancel(attempt.request)
            if not cancelled:
                raise ValueError(
                    "local transport failure occurred after attempt left pending state"
                )
            return NetworkFlowResult(
                route=attempt.route,
                transport_outcome=TransportOutcome.FAILURE,
                disposition=None,
                delivery_unknown=False,
                error=result.error,
            )

        if result.outcome is TransportOutcome.TIMEOUT:
            if completed_at < attempt.deadline:
                raise ValueError("transport timeout cannot complete before the registered deadline")
            expired = self._coordinator.expire(now=completed_at)
            if attempt.correlation not in expired:
                raise ValueError("timed-out attempt was not pending at its registered deadline")

            reversal_correlation = self._reversal_correlations.next_for(
                original=attempt.correlation,
                route=attempt.route,
            )
            link = self._reversals.link(
                original=attempt.correlation,
                reversal=reversal_correlation,
                reason=ReversalReason.TIMEOUT,
            )
            return NetworkFlowResult(
                route=attempt.route,
                transport_outcome=TransportOutcome.TIMEOUT,
                disposition=TransactionDisposition.TIMED_OUT,
                delivery_unknown=True,
                reversal=link,
                error=result.error,
            )

        assert result.response is not None
        if completed_at >= attempt.deadline:
            self._coordinator.expire(now=completed_at)
        disposition = self._coordinator.handle_response(
            attempt.request,
            result.response,
            now=completed_at,
        )
        return NetworkFlowResult(
            route=attempt.route,
            transport_outcome=TransportOutcome.RESPONSE,
            disposition=disposition,
            delivery_unknown=False,
        )

    def handle_late_response(
        self,
        attempt: NetworkAttempt,
        response: ISO8583Message,
        *,
        now: float,
    ) -> TransactionDisposition:
        """Apply an asynchronously received response after a prior exchange outcome."""

        disposition = self._coordinator.handle_response(
            attempt.request,
            response,
            now=now,
        )
        if self._telemetry is not None:
            self._telemetry.record_late_response(attempt.route, disposition)
        return disposition
