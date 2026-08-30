import os
from uuid import uuid4

import psycopg
import pytest

from app.ledger import LedgerAccount, PostgresLedger
from app.migrations import migrate_database
from app.models import CreatePaymentRequest
from app.payment_operations import (
    InvalidPaymentTransitionError,
    OperationIdempotencyConflictError,
    PaymentOperation,
    PostgresPaymentOperations,
)
from app.repository import PostgresPaymentRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


def create_payment(*, status: str = "authorized", amount: int = 12_900) -> str:
    assert DATABASE_URL is not None
    repository = PostgresPaymentRepository(DATABASE_URL)
    payment = repository.create_payment(
        CreatePaymentRequest(
            amount=amount,
            currency="MAD",
            merchant_reference=f"order-{uuid4().hex}",
        )
    )
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE payments SET status = %s WHERE id = %s", (status, payment.id))
    return payment.id


def create_account() -> str:
    assert DATABASE_URL is not None
    ledger = PostgresLedger(DATABASE_URL)
    account = LedgerAccount(
        id=f"acct_{uuid4().hex}",
        name=f"ops-{uuid4().hex}",
        currency="MAD",
    )
    return ledger.create_account(account).id


def test_capture_changes_state_and_posts_balanced_journal_atomically() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment()
    settlement = create_account()
    merchant = create_account()
    operations = PostgresPaymentOperations(DATABASE_URL)

    result = operations.execute(
        payment_id=payment_id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=settlement,
        destination_account_id=merchant,
        idempotency_key=f"capture-{uuid4().hex}",
    )

    assert result.from_status.value == "authorized"
    assert result.to_status.value == "captured"
    assert result.replayed is False

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT status FROM payments WHERE id = %s", (payment_id,))
        assert cursor.fetchone()[0] == "captured"
        cursor.execute(
            """
            SELECT side, amount
            FROM ledger_entries
            WHERE transaction_id = %s
            ORDER BY side
            """,
            (result.journal_transaction_id,),
        )
        assert cursor.fetchall() == [("credit", 12_900), ("debit", 12_900)]


def test_operation_replay_returns_original_result_without_duplicate_journal() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment()
    settlement = create_account()
    merchant = create_account()
    key = f"capture-{uuid4().hex}"
    operations = PostgresPaymentOperations(DATABASE_URL)

    first = operations.execute(
        payment_id=payment_id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=settlement,
        destination_account_id=merchant,
        idempotency_key=key,
    )
    replay = operations.execute(
        payment_id=payment_id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=settlement,
        destination_account_id=merchant,
        idempotency_key=key,
    )

    assert replay.operation_id == first.operation_id
    assert replay.journal_transaction_id == first.journal_transaction_id
    assert replay.replayed is True

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM payment_operations WHERE idempotency_key = %s",
            (key,),
        )
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT COUNT(*) FROM ledger_transactions WHERE id = %s",
            (first.journal_transaction_id,),
        )
        assert cursor.fetchone()[0] == 1


def test_conflicting_operation_key_is_rejected() -> None:
    assert DATABASE_URL is not None
    first_payment = create_payment()
    second_payment = create_payment()
    settlement = create_account()
    merchant = create_account()
    key = f"shared-{uuid4().hex}"
    operations = PostgresPaymentOperations(DATABASE_URL)

    operations.execute(
        payment_id=first_payment,
        operation=PaymentOperation.CAPTURE,
        source_account_id=settlement,
        destination_account_id=merchant,
        idempotency_key=key,
    )

    with pytest.raises(OperationIdempotencyConflictError):
        operations.execute(
            payment_id=second_payment,
            operation=PaymentOperation.CAPTURE,
            source_account_id=settlement,
            destination_account_id=merchant,
            idempotency_key=key,
        )


def test_invalid_transition_rolls_back_without_operation_or_journal() -> None:
    assert DATABASE_URL is not None
    payment_id = create_payment(status="pending")
    settlement = create_account()
    merchant = create_account()
    key = f"invalid-{uuid4().hex}"
    operations = PostgresPaymentOperations(DATABASE_URL)

    with pytest.raises(InvalidPaymentTransitionError, match="expected authorized"):
        operations.execute(
            payment_id=payment_id,
            operation=PaymentOperation.CAPTURE,
            source_account_id=settlement,
            destination_account_id=merchant,
            idempotency_key=key,
        )

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM payment_operations WHERE idempotency_key = %s",
            (key,),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT status FROM payments WHERE id = %s", (payment_id,))
        assert cursor.fetchone()[0] == "pending"
