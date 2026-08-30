from prometheus_client import CollectorRegistry, generate_latest

from app.network_coordinator import TransactionDisposition
from app.network_observability import NetworkTelemetry
from app.network_routing import IssuerRoute, ReversalReason
from app.network_transport import TransportOutcome


def route() -> IssuerRoute:
    return IssuerRoute(
        name="issuer-a",
        acquirer_id="atlas-acquirer",
        issuer_id="issuer-bank-a",
        pan_prefix="411111",
        currencies=frozenset({"MAD"}),
    )


def metrics_text(telemetry: NetworkTelemetry) -> str:
    return generate_latest(telemetry.registry).decode("utf-8")


def test_exchange_records_low_cardinality_outcome_and_reversal_metrics() -> None:
    telemetry = NetworkTelemetry(registry=CollectorRegistry())

    with telemetry.observe_exchange(route()) as observation:
        observation.transport_outcome = TransportOutcome.TIMEOUT
        observation.disposition = TransactionDisposition.TIMED_OUT
        observation.delivery_unknown = True
        observation.reversal_reason = ReversalReason.TIMEOUT

    output = metrics_text(telemetry)

    expected_attempt = (
        'atlaspay_network_attempts_total{issuer="issuer-bank-a",route="issuer-a"} 1.0'
    )
    assert expected_attempt in output
    assert 'transport_outcome="timeout"' in output
    assert 'disposition="timed_out"' in output
    assert 'delivery_unknown="true"' in output
    assert 'reason="timeout"' in output


def test_metric_surface_does_not_include_transaction_identifiers() -> None:
    telemetry = NetworkTelemetry(registry=CollectorRegistry())

    with telemetry.observe_exchange(route()) as observation:
        observation.transport_outcome = TransportOutcome.RESPONSE
        observation.disposition = TransactionDisposition.ACCEPTED

    output = metrics_text(telemetry)

    assert "pan" not in output.lower()
    assert "stan" not in output.lower()
    assert "rrn" not in output.lower()
    assert "de55" not in output.lower()


def test_late_response_is_recorded_separately_from_synchronous_exchange() -> None:
    telemetry = NetworkTelemetry(registry=CollectorRegistry())

    telemetry.record_late_response(route(), TransactionDisposition.LATE)

    output = metrics_text(telemetry)
    assert 'transport_outcome="async_response"' in output
    assert 'disposition="late"' in output
