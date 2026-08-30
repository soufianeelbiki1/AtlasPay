"""Failure-aware coordinator for request/response network transactions.

This module deliberately owns correlation and lifecycle semantics, while ISO 8583
encoding/decoding remains in the boundary adapter.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.canonical import NetworkCorrelation
from app.iso8583 import ISO8583Message
from app.iso8583_adapter import correlates_response, correlation_key


class TransactionDisposition(StrEnum):
    ACCEPTED = "accepted"
    MISMATCHED = "mismatched"
    TIMED_OUT = "timed_out"
    LATE = "late"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class PendingTransaction:
    correlation: NetworkCorrelation
    deadline: float


class NetworkTransactionCoordinator:
    """Tracks one-shot request lifecycles with explicit failure outcomes."""

    def __init__(self) -> None:
        self._pending: dict[NetworkCorrelation, PendingTransaction] = {}
        self._completed: set[NetworkCorrelation] = set()
        self._timed_out: set[NetworkCorrelation] = set()

    def register(
        self, request: ISO8583Message, *, now: float, timeout: float
    ) -> NetworkCorrelation:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        key = correlation_key(request)
        if key in self._pending or key in self._completed or key in self._timed_out:
            raise ValueError("correlation key is already in use")
        self._pending[key] = PendingTransaction(key, now + timeout)
        return key

    def cancel(self, request: ISO8583Message) -> bool:
        """Remove a pending request after a known-local pre-response failure.

        Cancellation is intentionally allowed only while the request is pending.
        It does not mark the correlation completed or timed out, so a caller may
        retry the same network correlation only when external delivery is known
        not to have occurred.
        """

        key = correlation_key(request)
        return self._pending.pop(key, None) is not None

    def expire(self, *, now: float) -> tuple[NetworkCorrelation, ...]:
        expired = tuple(
            sorted(key for key, transaction in self._pending.items() if transaction.deadline <= now)
        )
        for key in expired:
            self._pending.pop(key)
            self._timed_out.add(key)
        return expired

    def handle_response(
        self, request: ISO8583Message, response: ISO8583Message, *, now: float
    ) -> TransactionDisposition:
        key = correlation_key(response)
        if not correlates_response(request, response):
            return TransactionDisposition.MISMATCHED
        if key in self._completed:
            return TransactionDisposition.DUPLICATE
        if key in self._timed_out:
            self._timed_out.remove(key)
            self._completed.add(key)
            return TransactionDisposition.LATE
        transaction = self._pending.get(key)
        if transaction is None:
            return TransactionDisposition.MISMATCHED
        if transaction.deadline <= now:
            self._pending.pop(key)
            self._timed_out.add(key)
            return TransactionDisposition.TIMED_OUT
        self._pending.pop(key)
        self._completed.add(key)
        return TransactionDisposition.ACCEPTED
