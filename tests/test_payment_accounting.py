import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from app.ledger import PostgresLedger
from app.migrations import migrate_database
from app.models import CreatePaymentRequest, PaymentStatus
from app.payment_accounting import (
    InvalidPaymentTransitionError,
    OperationIdempotencyConflictError,
    PostgresPaymentAccounting,
)
from app.repository import PostgresPaymentRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


def create_payment(*, amount: int = 1000, currency: str = "MAD") -> str:
    assert DATABASE_URL is not None
    repository = PostgresPaymentRepository(DATABASE_URL)
    payment = repository.create_payment(
        CreatePaymentRequest(
            amount=amount,
            currency=currency,
            merchant_reference=f"acct-{uuid4().hex}",
        ),
        idempotency_key=f"create-{uuid4().hex}",
    )
    return payment.id


def accounting() -> PostgresPaymentAccounting:
    assert DATABASE_URL is not None
    return PostgresPaymentAccounting(DATABASE_URL)


def repository() -> PostgresPaymentRepository:
    assert DATABASE_URL is not None
    return PostgresPaymentRepository(DATABASE_URL)


def test_authorize_capture_and_refund_update_state_and_ledger_atomically() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment(amount=1200)
    store = accounting()

    authorization = store.authorize(
        payment_id=payment_id,
        amount=1200,
        idempotency_key=f"auth-{uuid4().hex}",
    )
    capture = store.capture(
        payment_id=payment_id,
        amount=1200,
        idempotency_key=f"capture-{uuid4().hex}",
    )

    payment = repository().get(payment_id)
    assert payment is not None
    assert payment.status is PaymentStatus.CAPTURED
    assert payment.authorized_amount == 1200
    assert payment.captured_amount == 1200
    assert payment.refunded_amount == 0
    assert authorization.journal_id is None
    assert capture.journal_id is not None

    refund = store.refund(
        payment_id=payment_id,
        amount=1200,
        idempotency_key=f"refund-{uuid4().hex}",
    )
    payment = repository().get(payment_id)
    assert payment is not None
    assert payment.status is PaymentStatus.REFUNDED
    assert payment.refunded_amount == 1200
    assert refund.journal_id is not None

    ledger = PostgresLedger(DATABASE_URL)
    clearing_id = "acct_settlement_clearing_mad"
    payable_id = "acct_merchant_payable_mad"
    assert ledger.account_balance(clearing_id) == 0
    assert ledger.account_balance(payable_id) == 0


def test_capture_retry_replays_same_operation_without_duplicate_journal() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment()
    store = accounting()
    store.authorize(
        payment_id=payment_id,
        amount=1000,
        idempotency_key=f"auth-{uuid4().hex}",
    )
    key = f"capture-{uuid4().hex}"

    first = store.capture(payment_id=payment_id, amount=1000, idempotency_key=key)
    second = store.capture(payment_id=payment_id, amount=1000, idempotency_key=key)

    assert second == first
    assert first.journal_id is not None

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM payment_operations WHERE idempotency_key = %s",
            (key,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT COUNT(*) FROM ledger_entries WHERE transaction_id = %s",
            (first.journal_id,),
        )
        assert cursor.fetchone()[0] == 2


def test_changed_request_with_same_operation_key_conflicts() -> None:
    payment_id = create_payment()
    store = accounting()
    store.authorize(
        payment_id=payment_id,
        amount=1000,
        idempotency_key=f"auth-{uuid4().hex}",
    )
    key = f"capture-{uuid4().hex}"
    store.capture(payment_id=payment_id, amount=400, idempotency_key=key)

    with pytest.raises(OperationIdempotencyConflictError):
        store.capture(payment_id=payment_id, amount=500, idempotency_key=key)


def test_failed_operation_does_not_consume_idempotency_key() -> None:
    payment_id = create_payment()
    store = accounting()
    store.authorize(
        payment_id=payment_id,
        amount=1000,
        idempotency_key=f"auth-{uuid4().hex}",
    )
    key = f"capture-{uuid4().hex}"

    with pytest.raises(InvalidPaymentTransitionError, match="exceed"):
        store.capture(payment_id=payment_id, amount=1500, idempotency_key=key)

    operation = store.capture(payment_id=payment_id, amount=1000, idempotency_key=key)
    assert operation.journal_id is not None


def test_refund_requires_fully_captured_payment() -> None:
    payment_id = create_payment()
    store = accounting()
    store.authorize(
        payment_id=payment_id,
        amount=1000,
        idempotency_key=f"auth-{uuid4().hex}",
    )
    store.capture(
        payment_id=payment_id,
        amount=400,
        idempotency_key=f"capture-{uuid4().hex}",
    )

    with pytest.raises(InvalidPaymentTransitionError, match="partially_captured"):
        store.refund(
            payment_id=payment_id,
            amount=100,
            idempotency_key=f"refund-{uuid4().hex}",
        )


def test_database_rejects_invalid_payment_accounting_counters() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment()

    with (
        pytest.raises(psycopg.errors.CheckViolation),
        psycopg.connect(DATABASE_URL) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(
            """
            UPDATE payments
            SET authorized_amount = 100, captured_amount = 200
            WHERE id = %s
            """,
            (payment_id,),
        )


def test_concurrent_capture_retries_converge_on_one_operation() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment()
    accounting().authorize(
        payment_id=payment_id,
        amount=1000,
        idempotency_key=f"auth-{uuid4().hex}",
    )
    key = f"capture-{uuid4().hex}"

    def capture_once(_: int) -> str:
        return accounting().capture(
            payment_id=payment_id,
            amount=1000,
            idempotency_key=key,
        ).id

    with ThreadPoolExecutor(max_workers=8) as executor:
        operation_ids = list(executor.map(capture_once, range(16)))

    assert len(set(operation_ids)) == 1

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM payment_operations WHERE idempotency_key = %s",
            (key,),
        )
        assert cursor.fetchone()[0] == 1
