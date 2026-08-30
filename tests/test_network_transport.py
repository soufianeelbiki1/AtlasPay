from dataclasses import dataclass

import pytest

from app.iso8583 import ISO8583Codec, ISO8583Message
from app.network_transport import (
    ISO8583NetworkAdapter,
    TransportExchange,
    TransportOutcome,
)


@dataclass
class ScriptedTransport:
    result: TransportExchange
    sent_payload: bytes | None = None
    timeout_seconds: float | None = None

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange:
        self.sent_payload = payload
        self.timeout_seconds = timeout_seconds
        return self.result


def request() -> ISO8583Message:
    return ISO8583Message("0200", {3: "000000", 11: "123456", 37: "ABC123456789"})


def response() -> ISO8583Message:
    return ISO8583Message("0210", {11: "123456", 37: "ABC123456789", 39: "00"})


def test_adapter_keeps_wire_encoding_at_transport_boundary() -> None:
    codec = ISO8583Codec()
    scripted = ScriptedTransport(
        TransportExchange(
            TransportOutcome.RESPONSE,
            response_payload=codec.encode(response()),
        )
    )
    adapter = ISO8583NetworkAdapter(scripted, codec)

    result = adapter.exchange(request(), timeout_seconds=2.5)

    assert scripted.sent_payload == codec.encode(request())
    assert scripted.timeout_seconds == 2.5
    assert result.outcome is TransportOutcome.RESPONSE
    assert result.response == response()
    assert result.delivery_unknown is False


def test_timeout_preserves_ambiguous_external_delivery() -> None:
    scripted = ScriptedTransport(
        TransportExchange(
            TransportOutcome.TIMEOUT,
            error="response deadline exceeded",
            delivery_unknown=True,
        )
    )

    result = ISO8583NetworkAdapter(scripted).exchange(request(), timeout_seconds=1.0)

    assert result.outcome is TransportOutcome.TIMEOUT
    assert result.response is None
    assert result.delivery_unknown is True


def test_local_transport_failure_does_not_become_delivery_claim() -> None:
    scripted = ScriptedTransport(
        TransportExchange(
            TransportOutcome.FAILURE,
            error="connection setup failed",
        )
    )

    result = ISO8583NetworkAdapter(scripted).exchange(request(), timeout_seconds=1.0)

    assert result.outcome is TransportOutcome.FAILURE
    assert result.delivery_unknown is False
    assert result.error == "connection setup failed"


def test_malformed_response_fails_at_adapter_boundary() -> None:
    scripted = ScriptedTransport(
        TransportExchange(
            TransportOutcome.RESPONSE,
            response_payload=b"not-an-iso-message",
        )
    )

    result = ISO8583NetworkAdapter(scripted).exchange(request(), timeout_seconds=1.0)

    assert result.outcome is TransportOutcome.FAILURE
    assert result.response is None
    assert result.error is not None
    assert result.error.startswith("invalid ISO 8583 response:")


def test_transport_exchange_invariants_reject_impossible_states() -> None:
    with pytest.raises(ValueError, match="requires response_payload"):
        TransportExchange(TransportOutcome.RESPONSE)
    with pytest.raises(ValueError, match="ambiguous external delivery"):
        TransportExchange(TransportOutcome.TIMEOUT)
    with pytest.raises(ValueError, match="must not claim ambiguous delivery"):
        TransportExchange(TransportOutcome.FAILURE, delivery_unknown=True)


def test_adapter_rejects_non_positive_timeout() -> None:
    scripted = ScriptedTransport(TransportExchange(TransportOutcome.FAILURE, error="unused"))

    with pytest.raises(ValueError, match="greater than zero"):
        ISO8583NetworkAdapter(scripted).exchange(request(), timeout_seconds=0)
