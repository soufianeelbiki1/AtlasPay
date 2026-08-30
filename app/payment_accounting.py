import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

import psycopg

from app.ledger import LedgerPosting, insert_journal
from app.models import PaymentStatus


class PaymentOperationType(StrEnum):
    AUTHORIZE = "authorize"
    CAPTURE = "capture"
    REFUND = "refund"


@dataclass(frozen=True)
class PaymentOperation:
    id: str
    payment_id: str
    operation_type: PaymentOperationType
    amount: int
    journal_id: str | None


class PaymentNotFoundError(LookupError):
    """Raised when a payment operation targets an unknown payment."""


class InvalidPaymentTransitionError(ValueError):
    """Raised when an operation violates payment-state or amount invariants."""


class OperationIdempotencyConflictError(ValueError):
    """Raised when an operation idempotency key is reused for a different request."""


class PostgresPaymentAccounting:
    """Atomic payment-state and ledger operations inside one PostgreSQL transaction."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _fingerprint(
        *,
        payment_id: str,
        operation_type: PaymentOperationType,
        amount: int,
    ) -> str:
        payload = json.dumps(
            {
                "amount": amount,
                "operation_type": operation_type.value,
                "payment_id": payment_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _row_to_operation(row: tuple[object, ...]) -> PaymentOperation:
        return PaymentOperation(
            id=str(row[0]),
            payment_id=str(row[1]),
            operation_type=PaymentOperationType(str(row[2])),
            amount=int(row[3]),
            journal_id=None if row[4] is None else str(row[4]),
        )

    @staticmethod
    def _control_account_id(role: str, currency: str) -> str:
        return f"acct_{role}_{currency.lower()}"

    @classmethod
    def _ensure_control_accounts(cls, cursor, currency: str) -> tuple[str, str]:
        clearing_id = cls._control_account_id("settlement_clearing", currency)
        payable_id = cls._control_account_id("merchant_payable", currency)
        cursor.executemany(
            """
            INSERT INTO ledger_accounts (id, name, currency)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            [
                (clearing_id, f"Settlement clearing {currency}", currency),
                (payable_id, f"Merchant payable {currency}", currency),
            ],
        )
        return clearing_id, payable_id

    @staticmethod
    def _load_payment_for_update(cursor, payment_id: str) -> tuple[object, ...]:
        cursor.execute(
            """
            SELECT id, amount, currency, status,
                   authorized_amount, captured_amount, refunded_amount
            FROM payments
            WHERE id = %s
            FOR UPDATE
            """,
            (payment_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise PaymentNotFoundError(payment_id)
        return row

    @classmethod
    def _claim_operation(
        cls,
        cursor,
        *,
        payment_id: str,
        operation_type: PaymentOperationType,
        amount: int,
        idempotency_key: str,
    ) -> tuple[str, PaymentOperation | None]:
        fingerprint = cls._fingerprint(
            payment_id=payment_id,
            operation_type=operation_type,
            amount=amount,
        )
        operation_id = f"op_{uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO payment_operations (
                id, payment_id, operation_type, amount,
                idempotency_key, request_fingerprint
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            (
                operation_id,
                payment_id,
                operation_type.value,
                amount,
                idempotency_key,
                fingerprint,
            ),
        )
        if cursor.fetchone() is not None:
            return operation_id, None

        cursor.execute(
            """
            SELECT id, payment_id, operation_type, amount, journal_id, request_fingerprint
            FROM payment_operations
            WHERE idempotency_key = %s
            """,
            (idempotency_key,),
        )
        existing = cursor.fetchone()
        if existing is None:
            raise RuntimeError("Operation idempotency claim disappeared")

        if str(existing[5]) != fingerprint:
            raise OperationIdempotencyConflictError(
                "Operation idempotency key was already used for a different request"
            )
        return str(existing[0]), cls._row_to_operation(existing[:5])

    @staticmethod
    def _update_operation_journal(cursor, operation_id: str, journal_id: str) -> None:
        cursor.execute(
            "UPDATE payment_operations SET journal_id = %s WHERE id = %s",
            (journal_id, operation_id),
        )

    @staticmethod
    def _load_operation(cursor, operation_id: str) -> PaymentOperation:
        cursor.execute(
            """
            SELECT id, payment_id, operation_type, amount, journal_id
            FROM payment_operations
            WHERE id = %s
            """,
            (operation_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Payment operation disappeared before commit")
        return PostgresPaymentAccounting._row_to_operation(row)

    def authorize(
        self,
        *,
        payment_id: str,
        amount: int,
        idempotency_key: str,
    ) -> PaymentOperation:
        if amount <= 0:
            raise InvalidPaymentTransitionError("Authorization amount must be positive")

        with self._connect() as conn, conn.cursor() as cursor:
            payment = self._load_payment_for_update(cursor, payment_id)
            operation_id, replay = self._claim_operation(
                cursor,
                payment_id=payment_id,
                operation_type=PaymentOperationType.AUTHORIZE,
                amount=amount,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return replay

            payment_amount = int(payment[1])
            status = PaymentStatus(str(payment[3]))
            if status is not PaymentStatus.PENDING:
                raise InvalidPaymentTransitionError(
                    f"Cannot authorize payment in {status.value} state"
                )
            if amount > payment_amount:
                raise InvalidPaymentTransitionError(
                    "Authorization amount cannot exceed the payment amount"
                )

            cursor.execute(
                """
                UPDATE payments
                SET status = %s, authorized_amount = %s
                WHERE id = %s
                """,
                (PaymentStatus.AUTHORIZED.value, amount, payment_id),
            )
            return self._load_operation(cursor, operation_id)

    def capture(
        self,
        *,
        payment_id: str,
        amount: int,
        idempotency_key: str,
    ) -> PaymentOperation:
        if amount <= 0:
            raise InvalidPaymentTransitionError("Capture amount must be positive")

        with self._connect() as conn, conn.cursor() as cursor:
            payment = self._load_payment_for_update(cursor, payment_id)
            operation_id, replay = self._claim_operation(
                cursor,
                payment_id=payment_id,
                operation_type=PaymentOperationType.CAPTURE,
                amount=amount,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return replay

            currency = str(payment[2]).upper()
            status = PaymentStatus(str(payment[3]))
            authorized_amount = int(payment[4])
            captured_amount = int(payment[5])
            if status not in {PaymentStatus.AUTHORIZED, PaymentStatus.PARTIALLY_CAPTURED}:
                raise InvalidPaymentTransitionError(
                    f"Cannot capture payment in {status.value} state"
                )
            new_captured = captured_amount + amount
            if new_captured > authorized_amount:
                raise InvalidPaymentTransitionError(
                    "Capture would exceed the authorized amount"
                )

            clearing_id, payable_id = self._ensure_control_accounts(cursor, currency)
            journal_id = insert_journal(
                cursor,
                reference=f"payment:{payment_id}:capture:{operation_id}",
                currency=currency,
                postings=[
                    LedgerPosting(account_id=clearing_id, side="debit", amount=amount),
                    LedgerPosting(account_id=payable_id, side="credit", amount=amount),
                ],
            )
            new_status = (
                PaymentStatus.CAPTURED
                if new_captured == authorized_amount
                else PaymentStatus.PARTIALLY_CAPTURED
            )
            cursor.execute(
                """
                UPDATE payments
                SET status = %s, captured_amount = %s
                WHERE id = %s
                """,
                (new_status.value, new_captured, payment_id),
            )
            self._update_operation_journal(cursor, operation_id, journal_id)
            return self._load_operation(cursor, operation_id)

    def refund(
        self,
        *,
        payment_id: str,
        amount: int,
        idempotency_key: str,
    ) -> PaymentOperation:
        if amount <= 0:
            raise InvalidPaymentTransitionError("Refund amount must be positive")

        with self._connect() as conn, conn.cursor() as cursor:
            payment = self._load_payment_for_update(cursor, payment_id)
            operation_id, replay = self._claim_operation(
                cursor,
                payment_id=payment_id,
                operation_type=PaymentOperationType.REFUND,
                amount=amount,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return replay

            currency = str(payment[2]).upper()
            captured_amount = int(payment[5])
            refunded_amount = int(payment[6])
            refundable = captured_amount - refunded_amount
            if amount > refundable:
                raise InvalidPaymentTransitionError(
                    "Refund would exceed the captured amount remaining"
                )

            clearing_id, payable_id = self._ensure_control_accounts(cursor, currency)
            journal_id = insert_journal(
                cursor,
                reference=f"payment:{payment_id}:refund:{operation_id}",
                currency=currency,
                postings=[
                    LedgerPosting(account_id=payable_id, side="debit", amount=amount),
                    LedgerPosting(account_id=clearing_id, side="credit", amount=amount),
                ],
            )
            new_refunded = refunded_amount + amount
            new_status = (
                PaymentStatus.REFUNDED
                if new_refunded == captured_amount
                else PaymentStatus.PARTIALLY_REFUNDED
            )
            cursor.execute(
                """
                UPDATE payments
                SET status = %s, refunded_amount = %s
                WHERE id = %s
                """,
                (new_status.value, new_refunded, payment_id),
            )
            self._update_operation_journal(cursor, operation_id, journal_id)
            return self._load_operation(cursor, operation_id)
