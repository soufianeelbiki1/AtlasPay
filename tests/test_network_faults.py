from dataclasses import dataclass

from app.network_faults import FaultInjectingTransport, FaultMode, FaultRule
from app.network_transport import TransportExchange, TransportOutcome


@dataclass
class RecordingTransport:
    calls: int = 0

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange:
        self.calls += 1
        assert payload
        assert timeout_seconds > 0
        return TransportExchange(TransportOutcome.RESPONSE, response_payload=b"upstream-response")


def test_fault_rule_triggers_on_configured_call_only() -> None:
    inner = RecordingTransport()
    transport = FaultInjectingTransport(
        inner,
        FaultRule(FaultMode.LOCAL_FAILURE, trigger_on_call=2),
    )

    first = transport.exchange(b"one", timeout_seconds=1.0)
    second = transport.exchange(b"two", timeout_seconds=1.0)
    third = transport.exchange(b"three", timeout_seconds=1.0)

    assert first.outcome is TransportOutcome.RESPONSE
    assert second.outcome is TransportOutcome.FAILURE
    assert "fault injection" in (second.error or "")
    assert third.outcome is TransportOutcome.RESPONSE
    assert inner.calls == 2
    assert transport.calls == 3


def test_timeout_fault_preserves_delivery_ambiguity() -> None:
    transport = FaultInjectingTransport(
        RecordingTransport(),
        FaultRule(FaultMode.TIMEOUT),
    )

    result = transport.exchange(b"request", timeout_seconds=0.5)

    assert result.outcome is TransportOutcome.TIMEOUT
    assert result.delivery_unknown is True
    assert result.response_payload is None


def test_malformed_response_fault_reaches_adapter_decode_boundary() -> None:
    transport = FaultInjectingTransport(
        RecordingTransport(),
        FaultRule(FaultMode.MALFORMED_RESPONSE),
    )

    result = transport.exchange(b"request", timeout_seconds=0.5)

    assert result.outcome is TransportOutcome.RESPONSE
    assert result.response_payload == b"fault-injected-invalid-iso8583"


def test_none_mode_is_transparent() -> None:
    inner = RecordingTransport()
    transport = FaultInjectingTransport(inner, FaultRule(FaultMode.NONE))

    result = transport.exchange(b"request", timeout_seconds=1.0)

    assert result.outcome is TransportOutcome.RESPONSE
    assert inner.calls == 1
