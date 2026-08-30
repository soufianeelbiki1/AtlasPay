import os
from pathlib import Path

import psycopg
import pytest

from app.migrations import migrate_database

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
ANALYTICS_DIR = Path(__file__).resolve().parents[1] / "analytics" / "sql"


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


@pytest.mark.parametrize(
    ("filename", "expected_columns"),
    [
        (
            "daily_payment_kpis.sql",
            [
                "payment_date",
                "currency",
                "payments_created",
                "gross_created_amount_minor",
                "average_created_amount_minor",
                "pending_payments",
                "authorized_payments",
                "captured_payments",
                "refunded_payments",
                "reversed_payments",
                "failed_payments",
                "cancelled_payments",
                "current_captured_share",
            ],
        ),
        (
            "payment_operation_latency.sql",
            [
                "operation_date",
                "currency",
                "operation",
                "operation_count",
                "average_seconds_after_creation",
                "p50_seconds_after_creation",
                "p95_seconds_after_creation",
            ],
        ),
        (
            "outbox_reliability.sql",
            [
                "event_date",
                "event_type",
                "total_events",
                "published_events",
                "unpublished_events",
                "retry_limit_events",
                "average_publish_latency_seconds",
                "p95_publish_latency_seconds",
                "max_attempts",
            ],
        ),
        (
            "ledger_daily_balance.sql",
            [
                "posting_date",
                "currency",
                "ledger_transactions",
                "ledger_entries",
                "debit_amount_minor",
                "credit_amount_minor",
                "debit_credit_difference_minor",
            ],
        ),
    ],
)
def test_analytics_mart_executes_against_migrated_schema(
    filename: str,
    expected_columns: list[str],
) -> None:
    assert DATABASE_URL is not None
    sql = (ANALYTICS_DIR / filename).read_text(encoding="utf-8")

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(sql)
        assert cursor.description is not None
        assert [column.name for column in cursor.description] == expected_columns


def test_analytics_queries_preserve_currency_in_every_monetary_grain() -> None:
    monetary_queries = [
        "daily_payment_kpis.sql",
        "payment_operation_latency.sql",
        "ledger_daily_balance.sql",
    ]

    for filename in monetary_queries:
        sql = (ANALYTICS_DIR / filename).read_text(encoding="utf-8").lower()
        assert "currency" in sql, f"{filename} must retain currency in its analytical grain"
