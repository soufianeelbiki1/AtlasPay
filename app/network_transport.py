"""Explicit network transport boundary for ISO 8583 message exchange.

The ISO 8583 codec owns message-body encoding. Concrete transports own sockets,
TLS, network headers, TPDU/framing, and remote endpoint behavior. A timeout is
explicitly ambiguous about external delivery: the request may have reached the
remote system even when AtlasPay received no response.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.iso8583 import ISO8583Codec, ISO8583CodecError, ISO8583Message


class TransportOutcome(StrEnum):
    RESPONSE = "response"
    TIMEOUT = "timeout"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class TransportExchange:
    outcome: TransportOutcome
    response_payload: bytes | None = None
    error: str | None = None
    delivery_unknown: bool = False

    def __post_init__(self) -> None:
        if self.outcome is TransportOutcome.RESPONSE:
            if self.response_payload is None:
                raise ValueError("response outcome requires response_payload")
            if self.error is not None or self.delivery_unknown:
                raise ValueError("response outcome cannot carry failure metadata")
        elif self.outcome is TransportOutcome.TIMEOUT:
            if self.response_payload is not None:
                raise ValueError("timeout outcome cannot carry response_payload")
            if not self.delivery_unknown:
                raise ValueError("timeout must preserve ambiguous external delivery")
        else:
            if self.response_payload is not None:
                raise ValueError("failure outcome cannot carry response_payload")
            if self.delivery_unknown:
                raise ValueError("local transport failure must not claim ambiguous delivery")


class NetworkTransport(Protocol):
    """Byte-oriented transport port.

    Implementations may use TCP/TLS, network-specific framing, or a simulator.
    They must not return decoded ISO 8583 objects.
    """

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange: ...


@dataclass(frozen=True, slots=True)
class ISO8583ExchangeResult:
    outcome: TransportOutcome
    response: ISO8583Message | None = None
    error: str | None = None
    delivery_unknown: bool = False


class ISO8583NetworkAdapter:
    """Encode/decode ISO 8583 bodies around an explicit byte transport."""

    def __init__(
        self,
        transport: NetworkTransport,
        codec: ISO8583Codec | None = None,
    ) -> None:
        self._transport = transport
        self._codec = codec or ISO8583Codec()

    def exchange(
        self,
        request: ISO8583Message,
        *,
        timeout_seconds: float,
    ) -> ISO8583ExchangeResult:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        payload = self._codec.encode(request)
        exchange = self._transport.exchange(payload, timeout_seconds=timeout_seconds)

        if exchange.outcome is TransportOutcome.TIMEOUT:
            return ISO8583ExchangeResult(
                outcome=TransportOutcome.TIMEOUT,
                error=exchange.error,
                delivery_unknown=True,
            )
        if exchange.outcome is TransportOutcome.FAILURE:
            return ISO8583ExchangeResult(
                outcome=TransportOutcome.FAILURE,
                error=exchange.error,
            )

        assert exchange.response_payload is not None
        try:
            response = self._codec.decode(exchange.response_payload)
        except ISO8583CodecError as exc:
            return ISO8583ExchangeResult(
                outcome=TransportOutcome.FAILURE,
                error=f"invalid ISO 8583 response: {exc}",
            )
        return ISO8583ExchangeResult(
            outcome=TransportOutcome.RESPONSE,
            response=response,
        )
