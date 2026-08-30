import os
from uuid import uuid4

import psycopg
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.ledger import LedgerAccount, LedgerInvariantError, LedgerPosting, PostgresLedger
from app.migrations import migrate_database

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    assert DATABASE_URL is not None
    migrate_database(DATABASE_URL)


def ledger() -> PostgresLedger:
    assert DATABASE_URL is not None
    return PostgresLedger(DATABASE_URL)


def create_account(store: PostgresLedger, *, currency: str = "MAD") -> LedgerAccount:
    account = LedgerAccount(
        id=f"acct_{uuid4().hex}",
        name=f"test-{uuid4().hex}",
        currency=currency,
    )
    return store.create_account(account)


def test_balanced_transaction_posts_atomically() -> None:
    store = ledger()
    cash = create_account(store)
    revenue = create_account(store)

    transaction_id = store.post(
        reference=f"payment-{uuid4().hex}",
        currency="mad",
        postings=[
            LedgerPosting(account_id=cash.id, side="debit", amount=12900),
            LedgerPosting(account_id=revenue.id, side="credit", amount=12900),
        ],
    )

    assert transaction_id.startswith("jrn_")
    assert store.account_balance(cash.id) == 12900
    assert store.account_balance(revenue.id) == -12900


def test_unbalanced_postings_are_rejected_before_database_write() -> None:
    store = ledger()
    cash = create_account(store)
    revenue = create_account(store)

    with pytest.raises(LedgerInvariantError, match="Unbalanced postings"):
        store.post(
            reference=f"bad-{uuid4().hex}",
            currency="MAD",
            postings=[
                LedgerPosting(account_id=cash.id, side="debit", amount=1000),
                LedgerPosting(account_id=revenue.id, side="credit", amount=999),
            ],
        )


def test_currency_mismatch_is_rejected_by_database_constraint() -> None:
    store = ledger()
    mad_account = create_account(store, currency="MAD")
    eur_account = create_account(store, currency="EUR")

    with pytest.raises(LedgerInvariantError):
        store.post(
            reference=f"fx-{uuid4().hex}",
            currency="MAD",
            postings=[
                LedgerPosting(account_id=mad_account.id, side="debit", amount=500),
                LedgerPosting(account_id=eur_account.id, side="credit", amount=500),
            ],
        )


def test_ledger_entries_are_append_only() -> None:
    assert DATABASE_URL is not None
    store = ledger()
    left = create_account(store)
    right = create_account(store)
    transaction_id = store.post(
        reference=f"immutable-{uuid4().hex}",
        currency="MAD",
        postings=[
            LedgerPosting(account_id=left.id, side="debit", amount=300),
            LedgerPosting(account_id=right.id, side="credit", amount=300),
        ],
    )

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM ledger_entries WHERE transaction_id = %s ORDER BY id LIMIT 1",
            (transaction_id,),
        )
        entry_id = cursor.fetchone()[0]

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            cursor.execute(
                "UPDATE ledger_entries SET amount = amount + 1 WHERE id = %s",
                (entry_id,),
            )
        conn.rollback()


def test_database_rejects_unbalanced_direct_writes_at_commit() -> None:
    assert DATABASE_URL is not None
    store = ledger()
    account = create_account(store)
    error_pattern = "requires at least one debit and one credit"

    with (
        pytest.raises(psycopg.errors.RaiseException, match=error_pattern),
        psycopg.connect(DATABASE_URL) as conn,
        conn.cursor() as cursor,
    ):
        transaction_id = f"jrn_{uuid4().hex}"
        cursor.execute(
            """
            INSERT INTO ledger_transactions (id, reference, currency)
            VALUES (%s, %s, %s)
            """,
            (transaction_id, f"direct-{uuid4().hex}", "MAD"),
        )
        cursor.execute(
            """
            INSERT INTO ledger_entries (
                transaction_id, account_id, side, amount, currency
            )
            VALUES (%s, %s, 'debit', 100, 'MAD')
            """,
            (transaction_id, account.id),
        )


def test_posted_transaction_metadata_is_immutable() -> None:
    assert DATABASE_URL is not None
    store = ledger()
    left = create_account(store)
    right = create_account(store)
    transaction_id = store.post(
        reference=f"immutable-journal-{uuid4().hex}",
        currency="MAD",
        postings=[
            LedgerPosting(account_id=left.id, side="debit", amount=200),
            LedgerPosting(account_id=right.id, side="credit", amount=200),
        ],
    )

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cursor:
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cursor.execute(
                "UPDATE ledger_transactions SET reference = %s WHERE id = %s",
                ("rewritten", transaction_id),
            )
        conn.rollback()


@given(amount=st.integers(min_value=1, max_value=10_000_000))
@settings(max_examples=10)
def test_equal_opposite_postings_preserve_zero_sum(amount: int) -> None:
    store = ledger()
    debit_account = create_account(store)
    credit_account = create_account(store)

    store.post(
        reference=f"property-{uuid4().hex}",
        currency="MAD",
        postings=[
            LedgerPosting(account_id=debit_account.id, side="debit", amount=amount),
            LedgerPosting(account_id=credit_account.id, side="credit", amount=amount),
        ],
    )

    total_balance = store.account_balance(debit_account.id) + store.account_balance(
        credit_account.id
    )
    assert total_balance == 0
