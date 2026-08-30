import json
import os
from uuid import uuid4

import psycopg
import pytest

from app.migrations import migrate_database
from app.models import CreatePaymentRequest
from app.operational_snapshot import PostgresOperationalSnapshotReader, SectionState
from app.repository import PostgresPaymentRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


def test_snapshot_measures_real_postgres_payment_and_poison_outbox_state() -> None:
    assert DATABASE_URL is not None
    marker = uuid4().hex
    payment = PostgresPaymentRepository(DATABASE_URL).create_payment(
        CreatePaymentRequest(
            amount=4300,
            currency="MAD",
            merchant_reference=f"ops-snapshot-{marker}",
        )
    )
    event_id = f"evt_ops_{marker}"

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO outbox_events (
                id, aggregate_type, aggregate_id, event_type, payload, attempts, last_error
            )
            VALUES (%s, 'diagnostic', %s, 'diagnostic.poison', %s::jsonb, 5, 'test failure')
            """,
            (event_id, payment.id, json.dumps({"fixture": marker})),
        )

    snapshot = PostgresOperationalSnapshotReader(DATABASE_URL).read()

    assert snapshot.payments.state is SectionState.AVAILABLE
    assert snapshot.payments.total is not None and snapshot.payments.total >= 1
    assert snapshot.payments.by_status is not None
    assert snapshot.payments.by_status.get("pending", 0) >= 1
    assert snapshot.outbox.state is SectionState.AVAILABLE
    assert snapshot.outbox.unpublished is not None and snapshot.outbox.unpublished >= 1
    assert snapshot.outbox.poison_messages is not None and snapshot.outbox.poison_messages >= 1
    assert snapshot.outbox.oldest_unpublished_age_seconds is not None
    assert snapshot.ledger.state is SectionState.AVAILABLE
    assert snapshot.ledger.inspected_at is not None
    assert snapshot.network.state is SectionState.UNAVAILABLE
    assert snapshot.missing_sections == ["network"]
