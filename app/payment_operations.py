import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

import psycopg

from app.models import PaymentStatus


class PaymentOperation(StrEnum):
    CAPTURE = "capture"
    REFUND = "refund"
    REVERSAL = "reversal"


@dataclass(frozen=True)
class OperationResult:
    operation_id: str
    payment_id: str
    operation: PaymentOperation
    from_status: PaymentStatus
    to_status: PaymentStatus
    journal_transaction_id: str
    replayed: bool


class PaymentOperationError(ValueError):
    """Base error for invalid or conflicting payment operations."""


class OperationIdempotencyConflictError(PaymentOperationError):
    """Raised when an operation idempotency key is reused for another request."""


class InvalidPaymentTransitionError(PaymentOperationError):
    """Raised when an operation is invalid for the current payment state."""


_TRANSITIONS: dict[PaymentOperation, tuple[PaymentStatus, PaymentStatus]] = {
    PaymentOperation.CAPTURE: (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURED),
    PaymentOperation.REFUND: (PaymentStatus.CAPTURED, PaymentStatus.REFUNDED),
    PaymentOperation.REVERSAL: (PaymentStatus.AUTHORIZED, PaymentStatus.REVERSED),
}


class PostgresPaymentOperations:
    """Atomically changes payment state and posts the matching double-entry journal.

    The operation idempotency key is serialized with a PostgreSQL advisory transaction
    lock. Payment state is locked with SELECT ... FOR UPDATE. State mutation, journal
    creation, ledger entries, and the operation record commit in one transaction.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _fingerprint(
        *,
        payment_id: str,
        operation: PaymentOperation,
        source_account_id: str,
        destination_account_id: str,
    ) -> str:
        payload = json.dumps(
            {
                "destination_account_id": destination_account_id,
                "operation": operation.value,
                "payment_id": payment_id,
                "source_account_id": source_account_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _result_from_row(row: tuple[object, ...], *, replayed: bool) -> OperationResult:
        return OperationResult(
            operation_id=str(row[0]),
            payment_id=str(row[1]),
            operation=PaymentOperation(str(row[2])),
            from_status=PaymentStatus(str(row[3])),
            to_status=PaymentStatus(str(row[4])),
            journal_transaction_id=str(row[5]),
            replayed=replayed,
        )

    def execute(
        self,
        *,
        payment_id: str,
        operation: PaymentOperation,
        source_account_id: str,
        destination_account_id: str,
        idempotency_key: str,
    ) -> OperationResult:
        if not idempotency_key.strip():
            raise PaymentOperationError("Operation idempotency key must not be empty")
        if source_account_id == destination_account_id:
            raise PaymentOperationError("Ledger source and destination accounts must differ")

        fingerprint = self._fingerprint(
            payment_id=payment_id,
            operation=operation,
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
        )
        expected_from, target_status = _TRANSITIONS[operation]

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (idempotency_key,))
            cursor.execute(
                """
                SELECT id, payment_id, operation, from_status, to_status,
                       journal_transaction_id, request_fingerprint
                FROM payment_operations
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                if existing[6] != fingerprint:
                    raise OperationIdempotencyConflictError(
                        "Operation idempotency key was already used with a different request"
                    )
                return self._result_from_row(existing[:6], replayed=True)

            cursor.execute(
                """
                SELECT status, amount, currency
                FROM payments
                WHERE id = %s
                FOR UPDATE
                """,
                (payment_id,),
            )
            payment = cursor.fetchone()
            if payment is None:
                raise PaymentOperationError(f"Payment {payment_id} does not exist")

            current_status = PaymentStatus(str(payment[0]))
            amount = int(payment[1])
            currency = str(payment[2]).upper()
            if current_status is not expected_from:
                raise InvalidPaymentTransitionError(
                    f"Cannot {operation.value} payment in {current_status.value} state; "
                    f"expected {expected_from.value}"
                )

            operation_id = f"op_{uuid4().hex}"
            journal_id = f"jrn_{uuid4().hex}"
            reference = f"payment:{payment_id}:{operation.value}:{operation_id}"

            cursor.execute(
                """
                INSERT INTO ledger_transactions (id, reference, currency)
                VALUES (%s, %s, %s)
                """,
                (journal_id, reference, currency),
            )
            cursor.executemany(
                """
                INSERT INTO ledger_entries (
                    transaction_id, account_id, side, amount, currency
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (journal_id, source_account_id, "debit", amount, currency),
                    (journal_id, destination_account_id, "credit", amount, currency),
                ],
            )
            cursor.execute(
                "UPDATE payments SET status = %s WHERE id = %s",
                (target_status.value, payment_id),
            )
            cursor.execute(
                """
                INSERT INTO payment_operations (
                    id, idempotency_key, request_fingerprint, payment_id, operation,
                    from_status, to_status, journal_transaction_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    operation_id,
                    idempotency_key,
                    fingerprint,
                    payment_id,
                    operation.value,
                    current_status.value,
                    target_status.value,
                    journal_id,
                ),
            )

        return OperationResult(
            operation_id=operation_id,
            payment_id=payment_id,
            operation=operation,
            from_status=current_status,
            to_status=target_status,
            journal_transaction_id=journal_id,
            replayed=False,
        )
