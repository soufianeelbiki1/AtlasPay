import os
from uuid import uuid4

import psycopg
import pytest

from app.ledger import LedgerAccount, PostgresLedger
from app.migrations import migrate_database
from app.models import CreatePaymentRequest
from app.outbox import OutboxEvent, PostgresOutbox
from app.payment_operations import PaymentOperation, PostgresPaymentOperations
from app.repository import PostgresPaymentRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


def create_account() -> str:
    assert DATABASE_URL is not None
    store = PostgresLedger(DATABASE_URL)
    return store.create_account(
        LedgerAccount(
            id=f"acct_{uuid4().hex}",
            name=f"outbox-{uuid4().hex}",
            currency="MAD",
        )
    ).id


def create_authorized_payment() -> str:
    assert DATABASE_URL is not None
    payment = PostgresPaymentRepository(DATABASE_URL).create_payment(
        CreatePaymentRequest(
            amount=4200,
            currency="MAD",
            merchant_reference=f"outbox-{uuid4().hex}",
        )
    )
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "UPDATE payments SET status = 'authorized' WHERE id = %s",
            (payment.id,),
        )
    return payment.id


def test_payment_operation_persists_domain_event_in_same_commit() -> None:
    assert DATABASE_URL is not None
    payment_id = create_authorized_payment()
    result = PostgresPaymentOperations(DATABASE_URL).execute(
        payment_id=payment_id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=create_account(),
        destination_account_id=create_account(),
        idempotency_key=f"outbox-capture-{uuid4().hex}",
    )

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT event_type, payload
            FROM outbox_events
            WHERE aggregate_id = %s
            """,
            (payment_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row[0] == "payment.captured"
    assert row[1]["operation_id"] == result.operation_id
    assert row[1]["journal_transaction_id"] == result.journal_transaction_id


def test_operation_replay_does_not_duplicate_outbox_event() -> None:
    assert DATABASE_URL is not None
    payment_id = create_authorized_payment()
    source = create_account()
    destination = create_account()
    key = f"outbox-replay-{uuid4().hex}"
    operations = PostgresPaymentOperations(DATABASE_URL)

    operations.execute(
        payment_id=payment_id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=source,
        destination_account_id=destination,
        idempotency_key=key,
    )
    operations.execute(
        payment_id=payment_id,
        operation=PaymentOperation.CAPTURE,
        source_account_id=source,
        destination_account_id=destination,
        idempotency_key=key,
    )

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM outbox_events WHERE aggregate_id = %s",
            (payment_id,),
        )
        assert cursor.fetchone()[0] == 1


def insert_event() -> str:
    assert DATABASE_URL is not None
    event_id = f"evt_{uuid4().hex}"
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO outbox_events (
                id, aggregate_type, aggregate_id, event_type, payload
            )
            VALUES (%s, 'payment', %s, 'payment.test', '{"value": 1}'::jsonb)
            """,
            (event_id, f"pay_{uuid4().hex}"),
        )
    return event_id


def test_publisher_marks_success_and_records_failed_attempts() -> None:
    assert DATABASE_URL is not None
    success_id = insert_event()
    failure_id = insert_event()
    outbox = PostgresOutbox(DATABASE_URL)

    def publish(event: OutboxEvent) -> None:
        if event.id == failure_id:
            raise RuntimeError("broker unavailable")

    assert outbox.publish_batch(publish, batch_size=100) >= 1

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT published_at, attempts, last_error FROM outbox_events WHERE id = %s",
            (success_id,),
        )
        success = cursor.fetchone()
        cursor.execute(
            "SELECT published_at, attempts, last_error FROM outbox_events WHERE id = %s",
            (failure_id,),
        )
        failure = cursor.fetchone()

    assert success[0] is not None
    assert success[1] == 1
    assert success[2] is None
    assert failure[0] is None
    assert failure[1] == 1
    assert "broker unavailable" in failure[2]


def test_consumer_deduplicates_event_id() -> None:
    assert DATABASE_URL is not None
    outbox = PostgresOutbox(DATABASE_URL)
    handled: list[str] = []
    event = OutboxEvent(
        id=f"evt_{uuid4().hex}",
        aggregate_type="payment",
        aggregate_id=f"pay_{uuid4().hex}",
        event_type="payment.captured",
        payload={"amount": 100},
        attempts=0,
    )

    first = outbox.consume_once(
        consumer_name="ledger-projection",
        event=event,
        handler=lambda current: handled.append(current.id),
    )
    replay = outbox.consume_once(
        consumer_name="ledger-projection",
        event=event,
        handler=lambda current: handled.append(current.id),
    )

    assert first is True
    assert replay is False
    assert handled == [event.id]
