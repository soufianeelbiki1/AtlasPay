import json
import os
from uuid import uuid4

import psycopg
import pytest

from app.ledger import LedgerAccount, PostgresLedger
from app.migrations import migrate_database
from app.models import CreatePaymentRequest
from app.outbox import PostgresOutbox
from app.payment_operations import PaymentOperation, PostgresPaymentOperations
from app.reconciliation import DiscrepancyKind, PostgresReconciler, PostgresReplayController
from app.repository import PostgresPaymentRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


def create_account() -> str:
    assert DATABASE_URL is not None
    ledger = PostgresLedger(DATABASE_URL)
    return ledger.create_account(
        LedgerAccount(
            id=f"acct_{uuid4().hex}",
            name=f"recon-{uuid4().hex}",
            currency="MAD",
        )
    ).id


def create_operation() -> tuple[str, str]:
    assert DATABASE_URL is not None
    payment = PostgresPaymentRepository(DATABASE_URL).create_payment(
        CreatePaymentRequest(
            amount=2500,
            currency="MAD",
            merchant_reference=f"recon-{uuid4().hex}",
        )
    )
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE payments SET status = 'authorized' WHERE id = %s", (payment.id,))
    result = PostgresPaymentOperations(DATABASE_URL).execute(
        payment_id=payment.id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=create_account(),
        destination_account_id=create_account(),
        idempotency_key=f"recon-{uuid4().hex}",
    )
    return payment.id, result.operation_id


def test_clean_operation_has_no_reconciliation_discrepancies() -> None:
    assert DATABASE_URL is not None
    create_operation()
    report = PostgresReconciler(DATABASE_URL).inspect()
    assert report.clean is True


def test_detects_payment_status_mismatch_and_missing_outbox() -> None:
    assert DATABASE_URL is not None
    payment_id, operation_id = create_operation()
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE payments SET status = 'authorized' WHERE id = %s", (payment_id,))
        cursor.execute(
            "DELETE FROM outbox_events WHERE payload->>'operation_id' = %s",
            (operation_id,),
        )

    report = PostgresReconciler(DATABASE_URL).inspect()
    kinds = {item.kind for item in report.discrepancies if item.entity_id == operation_id}
    assert DiscrepancyKind.PAYMENT_STATUS_MISMATCH in kinds
    assert DiscrepancyKind.OPERATION_WITHOUT_OUTBOX in kinds


def test_detects_orphan_outbox_operation_reference() -> None:
    assert DATABASE_URL is not None
    event_id = f"evt_{uuid4().hex}"
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO outbox_events (id, aggregate_type, aggregate_id, event_type, payload)
            VALUES (%s, 'payment', %s, 'payment.captured', %s::jsonb)
            """,
            (
                event_id,
                f"pay_{uuid4().hex}",
                json.dumps({"operation_id": f"op_{uuid4().hex}"}),
            ),
        )

    report = PostgresReconciler(DATABASE_URL).inspect()
    assert any(
        item.kind is DiscrepancyKind.OUTBOX_WITHOUT_OPERATION and item.entity_id == event_id
        for item in report.discrepancies
    )


def test_report_order_is_deterministic() -> None:
    assert DATABASE_URL is not None
    report = PostgresReconciler(DATABASE_URL).inspect()
    keys = [(item.kind.value, item.entity_id, item.detail) for item in report.discrepancies]
    assert keys == sorted(keys)


def test_replay_controller_resets_only_unpublished_events() -> None:
    assert DATABASE_URL is not None
    payment_id, operation_id = create_operation()
    outbox = PostgresOutbox(DATABASE_URL)

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM outbox_events WHERE payload->>'operation_id' = %s",
            (operation_id,),
        )
        event_id = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE outbox_events SET attempts = 5, last_error = 'boom' WHERE id = %s",
            (event_id,),
        )

    controller = PostgresReplayController(DATABASE_URL)
    assert controller.reset_outbox_event(event_id) is True

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT attempts, last_error FROM outbox_events WHERE id = %s", (event_id,))
        assert cursor.fetchone() == (0, None)

    assert outbox.publish_batch(lambda event: None) >= 1
    assert controller.reset_outbox_event(event_id) is False

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT published_at FROM outbox_events WHERE id = %s", (event_id,))
        assert cursor.fetchone()[0] is not None
