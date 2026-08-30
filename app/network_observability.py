"""Low-cardinality network observability for AtlasPay authorization flows.

Telemetry deliberately excludes PAN, STAN, RRN, DE55, and other transaction-level
identifiers from metric labels. Those values are high-cardinality and may be sensitive.
The OpenTelemetry API remains exporter-neutral; deployments choose an SDK/exporter.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer
from prometheus_client import CollectorRegistry, Counter, Histogram

from app.network_coordinator import TransactionDisposition
from app.network_routing import IssuerRoute, ReversalReason
from app.network_transport import TransportOutcome


@dataclass(slots=True)
class ExchangeObservation:
    """Mutable result carrier owned by one observation context."""

    transport_outcome: TransportOutcome | None = None
    disposition: TransactionDisposition | None = None
    delivery_unknown: bool = False
    reversal_reason: ReversalReason | None = None
    span: Span | None = None


class NetworkTelemetry:
    """Prometheus metrics plus OpenTelemetry spans for issuer exchanges.

    Metrics use route and issuer identity only. Transaction correlation belongs in
    trace context or protected logs, never in Prometheus labels.
    """

    def __init__(
        self,
        *,
        registry: CollectorRegistry | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        metric_registry = registry or CollectorRegistry(auto_describe=True)
        self.registry = metric_registry
        self._tracer = tracer or trace.get_tracer("atlaspay.network")
        self._attempts = Counter(
            "atlaspay_network_attempts_total",
            "Authorization network attempts by route and issuer.",
            ("route", "issuer"),
            registry=metric_registry,
        )
        self._outcomes = Counter(
            "atlaspay_network_outcomes_total",
            "Authorization network outcomes without transaction identifiers.",
            ("route", "issuer", "transport_outcome", "disposition", "delivery_unknown"),
            registry=metric_registry,
        )
        self._latency = Histogram(
            "atlaspay_network_exchange_seconds",
            "Issuer exchange latency in seconds.",
            ("route", "issuer", "transport_outcome"),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
            registry=metric_registry,
        )
        self._reversals = Counter(
            "atlaspay_network_reversal_plans_total",
            "Reversal correlations planned after ambiguous/exceptional outcomes.",
            ("route", "issuer", "reason"),
            registry=metric_registry,
        )

    @contextmanager
    def observe_exchange(self, route: IssuerRoute) -> Iterator[ExchangeObservation]:
        """Observe one issuer exchange and record its final classified outcome."""

        self._attempts.labels(route=route.name, issuer=route.issuer_id).inc()
        started = perf_counter()
        carrier = ExchangeObservation()
        with self._tracer.start_as_current_span("atlaspay.authorization.network_exchange") as span:
            carrier.span = span
            span.set_attribute("atlaspay.route", route.name)
            span.set_attribute("atlaspay.issuer", route.issuer_id)
            try:
                yield carrier
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("error.type", type(exc).__name__)
                raise
            finally:
                elapsed = perf_counter() - started
                outcome = carrier.transport_outcome or TransportOutcome.FAILURE
                disposition = carrier.disposition.value if carrier.disposition is not None else "none"
                delivery_unknown = "true" if carrier.delivery_unknown else "false"
                self._outcomes.labels(
                    route=route.name,
                    issuer=route.issuer_id,
                    transport_outcome=outcome.value,
                    disposition=disposition,
                    delivery_unknown=delivery_unknown,
                ).inc()
                self._latency.labels(
                    route=route.name,
                    issuer=route.issuer_id,
                    transport_outcome=outcome.value,
                ).observe(elapsed)
                span.set_attribute("atlaspay.transport_outcome", outcome.value)
                span.set_attribute("atlaspay.disposition", disposition)
                span.set_attribute("atlaspay.delivery_unknown", carrier.delivery_unknown)
                if carrier.reversal_reason is not None:
                    self._reversals.labels(
                        route=route.name,
                        issuer=route.issuer_id,
                        reason=carrier.reversal_reason.value,
                    ).inc()
                    span.set_attribute("atlaspay.reversal_reason", carrier.reversal_reason.value)

    def record_late_response(
        self,
        route: IssuerRoute,
        disposition: TransactionDisposition,
    ) -> None:
        """Record asynchronous late/duplicate response classification."""

        with self._tracer.start_as_current_span("atlaspay.authorization.late_response") as span:
            span.set_attribute("atlaspay.route", route.name)
            span.set_attribute("atlaspay.issuer", route.issuer_id)
            span.set_attribute("atlaspay.disposition", disposition.value)
            self._outcomes.labels(
                route=route.name,
                issuer=route.issuer_id,
                transport_outcome="async_response",
                disposition=disposition.value,
                delivery_unknown="false",
            ).inc()
