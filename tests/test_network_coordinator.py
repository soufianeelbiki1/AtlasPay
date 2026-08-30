import pytest

from app.iso8583 import ISO8583Message
from app.network_coordinator import NetworkTransactionCoordinator, TransactionDisposition


def request() -> ISO8583Message:
    return ISO8583Message("0200", {11: "123456", 37: "ABC123456789"})


def response(
    *, mti: str = "0210", stan: str = "123456", rrn: str = "ABC123456789"
) -> ISO8583Message:
    return ISO8583Message(mti, {11: stan, 37: rrn})


def test_timeout_then_late_response_is_explicit() -> None:
    coordinator = NetworkTransactionCoordinator()
    req = request()
    key = coordinator.register(req, now=10.0, timeout=5.0)

    assert coordinator.expire(now=15.0) == (key,)
    assert coordinator.handle_response(req, response(), now=16.0) is TransactionDisposition.LATE


def test_duplicate_response_is_not_reprocessed() -> None:
    coordinator = NetworkTransactionCoordinator()
    req = request()
    coordinator.register(req, now=0.0, timeout=10.0)

    assert coordinator.handle_response(req, response(), now=1.0) is TransactionDisposition.ACCEPTED
    assert coordinator.handle_response(req, response(), now=2.0) is TransactionDisposition.DUPLICATE


def test_mismatched_response_does_not_complete_request() -> None:
    coordinator = NetworkTransactionCoordinator()
    req = request()
    coordinator.register(req, now=0.0, timeout=10.0)

    assert (
        coordinator.handle_response(req, response(stan="654321"), now=1.0)
        is TransactionDisposition.MISMATCHED
    )


def test_registration_rejects_reuse_and_invalid_timeout() -> None:
    coordinator = NetworkTransactionCoordinator()
    req = request()
    with pytest.raises(ValueError, match="greater"):
        coordinator.register(req, now=0.0, timeout=0.0)
    coordinator.register(req, now=0.0, timeout=1.0)
    with pytest.raises(ValueError, match="already"):
        coordinator.register(req, now=0.0, timeout=1.0)
