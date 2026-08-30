"""Deterministic fault injection at the byte-oriented network transport boundary."""

from dataclasses import dataclass
from enum import StrEnum

from app.network_transport import NetworkTransport, TransportExchange, TransportOutcome


class FaultMode(StrEnum):
    NONE = "none"
    LOCAL_FAILURE = "local_failure"
    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"


@dataclass(frozen=True, slots=True)
class FaultRule:
    """Apply one deterministic fault on the Nth matching exchange.

    The rule is intentionally deterministic so CI can exercise exact failure paths.
    Probabilistic chaos belongs in a higher-level environment test, not unit tests.
    """

    mode: FaultMode
    trigger_on_call: int = 1

    def __post_init__(self) -> None:
        if self.trigger_on_call <= 0:
            raise ValueError("trigger_on_call must be positive")


class FaultInjectingTransport:
    """Wrap a real or scripted transport and inject a bounded deterministic fault."""

    def __init__(self, inner: NetworkTransport, rule: FaultRule) -> None:
        self._inner = inner
        self._rule = rule
        self._calls = 0

    @property
    def calls(self) -> int:
        return self._calls

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange:
        self._calls += 1
        if self._calls != self._rule.trigger_on_call or self._rule.mode is FaultMode.NONE:
            return self._inner.exchange(payload, timeout_seconds=timeout_seconds)

        if self._rule.mode is FaultMode.LOCAL_FAILURE:
            return TransportExchange(
                TransportOutcome.FAILURE,
                error="fault injection: local transport failure before response",
            )
        if self._rule.mode is FaultMode.TIMEOUT:
            return TransportExchange(
                TransportOutcome.TIMEOUT,
                error="fault injection: response deadline exceeded",
                delivery_unknown=True,
            )
        if self._rule.mode is FaultMode.MALFORMED_RESPONSE:
            return TransportExchange(
                TransportOutcome.RESPONSE,
                response_payload=b"fault-injected-invalid-iso8583",
            )
        raise AssertionError(f"unsupported fault mode: {self._rule.mode}")
