import hashlib
import json
import threading
from typing import Protocol

from app.models import CreatePaymentRequest, Payment


class IdempotencyConflictError(ValueError):
    """Raised when an idempotency key is reused with a different request."""


def request_fingerprint(request: CreatePaymentRequest) -> str:
    payload = json.dumps(request.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class PaymentRepository(Protocol):
    def create_payment(
        self,
        request: CreatePaymentRequest,
        idempotency_key: str | None = None,
    ) -> Payment: ...

    def get(self, payment_id: str) -> Payment | None: ...


class InMemoryPaymentRepository:
    """Process-local adapter that preserves the same atomic contract as durable stores."""

    def __init__(self) -> None:
        self._payments: dict[str, Payment] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def create_payment(
        self,
        request: CreatePaymentRequest,
        idempotency_key: str | None = None,
    ) -> Payment:
        fingerprint = request_fingerprint(request)

        with self._lock:
            if idempotency_key:
                existing = self._idempotency.get(idempotency_key)
                if existing is not None:
                    previous_fingerprint, payment_id = existing
                    if previous_fingerprint != fingerprint:
                        raise IdempotencyConflictError(
                            "Idempotency key was already used with a different request"
                        )
                    return self._payments[payment_id]

            payment = Payment(**request.model_dump())
            self._payments[payment.id] = payment
            if idempotency_key:
                self._idempotency[idempotency_key] = (fingerprint, payment.id)
            return payment

    def get(self, payment_id: str) -> Payment | None:
        return self._payments.get(payment_id)


class PostgresPaymentRepository:
    """PostgreSQL adapter with transactionally durable idempotency semantics.

    A unique constraint on ``idempotency_keys.key`` is the cross-worker arbiter. Competing
    requests may both construct candidate payments, but only one key claim can commit; losing
    candidates are deleted in the same transaction before the existing payment is returned.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        import psycopg

        return psycopg.connect(self._dsn)

    @staticmethod
    def _row_to_payment(row: tuple[object, ...] | None) -> Payment | None:
        if row is None:
            return None
        return Payment(
            id=row[0],
            amount=row[1],
            currency=row[2],
            merchant_reference=row[3],
            status=row[4],
            created_at=row[5],
        )

    @staticmethod
    def _insert_payment(cursor, payment: Payment) -> None:
        cursor.execute(
            """
            INSERT INTO payments (id, amount, currency, merchant_reference, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                payment.id,
                payment.amount,
                payment.currency,
                payment.merchant_reference,
                payment.status.value,
                payment.created_at,
            ),
        )

    def create_payment(
        self,
        request: CreatePaymentRequest,
        idempotency_key: str | None = None,
    ) -> Payment:
        payment = Payment(**request.model_dump())
        if not idempotency_key:
            with self._connect() as conn, conn.cursor() as cursor:
                self._insert_payment(cursor, payment)
            return payment

        fingerprint = request_fingerprint(request)
        conflict = False
        result: Payment | None = None

        with self._connect() as conn, conn.cursor() as cursor:
            self._insert_payment(cursor, payment)
            cursor.execute(
                """
                INSERT INTO idempotency_keys (key, request_fingerprint, payment_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO NOTHING
                RETURNING payment_id
                """,
                (idempotency_key, fingerprint, payment.id),
            )
            claimed = cursor.fetchone()
            if claimed is not None:
                result = payment
            else:
                cursor.execute("DELETE FROM payments WHERE id = %s", (payment.id,))
                cursor.execute(
                    """
                    SELECT request_fingerprint, payment_id
                    FROM idempotency_keys
                    WHERE key = %s
                    """,
                    (idempotency_key,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    raise RuntimeError("Idempotency claim disappeared during transaction")

                previous_fingerprint, existing_payment_id = existing
                if previous_fingerprint != fingerprint:
                    conflict = True
                else:
                    cursor.execute(
                        """
                        SELECT id, amount, currency, merchant_reference, status, created_at
                        FROM payments
                        WHERE id = %s
                        """,
                        (existing_payment_id,),
                    )
                    result = self._row_to_payment(cursor.fetchone())
                    if result is None:
                        raise RuntimeError("Idempotency record references a missing payment")

        if conflict:
            raise IdempotencyConflictError(
                "Idempotency key was already used with a different request"
            )
        if result is None:
            raise RuntimeError("Payment creation completed without a result")
        return result

    def get(self, payment_id: str) -> Payment | None:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, amount, currency, merchant_reference, status, created_at
                FROM payments
                WHERE id = %s
                """,
                (payment_id,),
            )
            return self._row_to_payment(cursor.fetchone())
