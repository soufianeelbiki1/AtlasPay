from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import psycopg

LedgerSide = Literal["debit", "credit"]


@dataclass(frozen=True)
class LedgerAccount:
    id: str
    name: str
    currency: str


@dataclass(frozen=True)
class LedgerPosting:
    account_id: str
    side: LedgerSide
    amount: int


class LedgerInvariantError(ValueError):
    """Raised when a posting set violates double-entry invariants."""


def validate_postings(postings: list[LedgerPosting]) -> None:
    if len(postings) < 2:
        raise LedgerInvariantError("A ledger transaction requires at least two postings")

    if any(posting.amount <= 0 for posting in postings):
        raise LedgerInvariantError("Ledger posting amounts must be positive")

    debit_total = sum(p.amount for p in postings if p.side == "debit")
    credit_total = sum(p.amount for p in postings if p.side == "credit")
    if debit_total != credit_total:
        raise LedgerInvariantError(
            f"Unbalanced postings: debits={debit_total}, credits={credit_total}"
        )


def insert_journal(
    cursor,
    *,
    reference: str,
    currency: str,
    postings: list[LedgerPosting],
    transaction_id: str | None = None,
) -> str:
    """Insert one balanced journal using the caller's database transaction."""
    validate_postings(postings)
    normalized_currency = currency.upper()
    if len(normalized_currency) != 3:
        raise LedgerInvariantError("Ledger transaction currency must be a 3-letter code")

    journal_id = transaction_id or f"jrn_{uuid4().hex}"
    cursor.execute(
        """
        INSERT INTO ledger_transactions (id, reference, currency)
        VALUES (%s, %s, %s)
        """,
        (journal_id, reference, normalized_currency),
    )
    cursor.executemany(
        """
        INSERT INTO ledger_entries (
            transaction_id, account_id, side, amount, currency
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        [
            (
                journal_id,
                posting.account_id,
                posting.side,
                posting.amount,
                normalized_currency,
            )
            for posting in postings
        ],
    )
    return journal_id


class PostgresLedger:
    """Append-only PostgreSQL double-entry ledger.

    All entries in one journal transaction must use the same currency as both the
    transaction and referenced accounts. PostgreSQL composite foreign keys enforce
    currency consistency, and a deferred constraint trigger rejects unbalanced
    postings at commit.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn)

    def create_account(self, account: LedgerAccount) -> LedgerAccount:
        currency = account.currency.upper()
        if len(currency) != 3:
            raise LedgerInvariantError("Ledger account currency must be a 3-letter code")

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ledger_accounts (id, name, currency)
                VALUES (%s, %s, %s)
                """,
                (account.id, account.name, currency),
            )
        return LedgerAccount(id=account.id, name=account.name, currency=currency)

    def post(
        self,
        *,
        reference: str,
        currency: str,
        postings: list[LedgerPosting],
        transaction_id: str | None = None,
    ) -> str:
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                return insert_journal(
                    cursor,
                    reference=reference,
                    currency=currency,
                    postings=postings,
                    transaction_id=transaction_id,
                )
        except psycopg.IntegrityError as exc:
            raise LedgerInvariantError(str(exc)) from exc

    def account_balance(self, account_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN side = 'debit' THEN amount
                            WHEN side = 'credit' THEN -amount
                            ELSE 0
                        END
                    ),
                    0
                )
                FROM ledger_entries
                WHERE account_id = %s
                """,
                (account_id,),
            )
            row = cursor.fetchone()

        if row is None:
            raise RuntimeError("Ledger balance query returned no row")
        return int(row[0])
