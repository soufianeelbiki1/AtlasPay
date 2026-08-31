from __future__ import annotations

import json
import os
from dataclasses import asdict
from uuid import uuid4

import psycopg

from app.models import CreatePaymentRequest, PaymentStatus
from app.payment_operations import PaymentOperation, PostgresPaymentOperations
from app.repository import PostgresPaymentRepository


def _require_database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for the AtlasPay demo seeder")
    return database_url


def _set_seed_status(database_url: str, payment_id: str, status: PaymentStatus) -> None:
    """Set a seed-only starting state before exercising real durable operations."""

    with psycopg.connect(database_url) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE payments SET status = %s WHERE id = %s",
            (status.value, payment_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Demo payment {payment_id} disappeared before seeding")


def seed_demo() -> dict[str, object]:
    """Create a compact, repeatable operator-demo dataset.

    The seed is intentionally synthetic. It uses the real PostgreSQL repository and
    payment-operation transaction path for capture/refund/reversal. Direct status writes
    are limited to establishing seed-only authorization/failure starting states because
    AtlasPay does not yet persist a full authorization-network fact model.
    """

    database_url = _require_database_url()
    repository = PostgresPaymentRepository(database_url)
    operations = PostgresPaymentOperations(database_url)
    run_id = uuid4().hex[:10]

    def create(label: str, amount: int, idempotency_key: str):
        request = CreatePaymentRequest(
            amount=amount,
            currency="MAD",
            merchant_reference=f"demo:{run_id}:{label}",
        )
        return repository.create_payment(request, idempotency_key)

    duplicate_key = f"demo:{run_id}:duplicate"
    duplicate_request = CreatePaymentRequest(
        amount=12900,
        currency="MAD",
        merchant_reference=f"demo:{run_id}:duplicate",
    )
    duplicate_first = repository.create_payment(duplicate_request, duplicate_key)
    duplicate_replay = repository.create_payment(duplicate_request, duplicate_key)
    if duplicate_first.id != duplicate_replay.id:
        raise RuntimeError("Durable idempotency replay returned a different payment")

    pending = create("pending", 7600, f"demo:{run_id}:pending")

    failed = create("failed", 8800, f"demo:{run_id}:failed")
    _set_seed_status(database_url, failed.id, PaymentStatus.FAILED)

    captured = create("captured", 21500, f"demo:{run_id}:captured")
    _set_seed_status(database_url, captured.id, PaymentStatus.AUTHORIZED)
    capture_result = operations.execute(
        payment_id=captured.id,
        operation=PaymentOperation.CAPTURE,
        source_account_id="card_receivable",
        destination_account_id="merchant_payable",
        idempotency_key=f"demo:{run_id}:capture-op",
    )

    refunded = create("refunded", 9900, f"demo:{run_id}:refunded")
    _set_seed_status(database_url, refunded.id, PaymentStatus.AUTHORIZED)
    operations.execute(
        payment_id=refunded.id,
        operation=PaymentOperation.CAPTURE,
        source_account_id="card_receivable",
        destination_account_id="merchant_payable",
        idempotency_key=f"demo:{run_id}:refund-capture-op",
    )
    refund_result = operations.execute(
        payment_id=refunded.id,
        operation=PaymentOperation.REFUND,
        source_account_id="merchant_payable",
        destination_account_id="card_receivable",
        idempotency_key=f"demo:{run_id}:refund-op",
    )

    reversed_payment = create("reversed", 18400, f"demo:{run_id}:reversed")
    _set_seed_status(database_url, reversed_payment.id, PaymentStatus.AUTHORIZED)
    reversal_result = operations.execute(
        payment_id=reversed_payment.id,
        operation=PaymentOperation.REVERSAL,
        source_account_id="merchant_reserve",
        destination_account_id="card_receivable",
        idempotency_key=f"demo:{run_id}:reversal-op",
    )

    summary = {
        "synthetic": True,
        "run_id": run_id,
        "payments": {
            "duplicate_idempotent": duplicate_first.id,
            "pending": pending.id,
            "failed": failed.id,
            "captured": captured.id,
            "refunded": refunded.id,
            "reversed": reversed_payment.id,
        },
        "operations": {
            "capture": asdict(capture_result),
            "refund": asdict(refund_result),
            "reversal": asdict(reversal_result),
        },
        "notes": [
            "All demo observations are synthetic.",
            "Capture/refund/reversal use the real durable operation transaction path.",
            "Authorization/failure seed states are direct demo setup until durable network facts exist.",
            "Idempotency replay is verified to return the original payment id.",
        ],
    }
    return summary


def main() -> None:
    print(json.dumps(seed_demo(), indent=2, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
