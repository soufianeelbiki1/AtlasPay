from dataclasses import dataclass
from enum import StrEnum

import psycopg


class DiscrepancyKind(StrEnum):
    OPERATION_WITHOUT_PAYMENT = "operation_without_payment"
    OPERATION_WITHOUT_JOURNAL = "operation_without_journal"
    OPERATION_WITHOUT_OUTBOX = "operation_without_outbox"
    OUTBOX_WITHOUT_OPERATION = "outbox_without_operation"
    PAYMENT_STATUS_MISMATCH = "payment_status_mismatch"
    JOURNAL_ENTRY_COUNT_INVALID = "journal_entry_count_invalid"
    JOURNAL_UNBALANCED = "journal_unbalanced"


@dataclass(frozen=True)
class ReconciliationDiscrepancy:
    kind: DiscrepancyKind
    entity_id: str
    detail: str


@dataclass(frozen=True)
class ReconciliationReport:
    discrepancies: tuple[ReconciliationDiscrepancy, ...]

    @property
    def clean(self) -> bool:
        return not self.discrepancies


class PostgresReconciler:
    """Produces deterministic cross-table consistency reports.

    This tool is intentionally read-only. Rebuild/replay actions must be explicit and
    targeted rather than silently mutating accounting or payment state.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn)

    def inspect(self) -> ReconciliationReport:
        discrepancies: list[ReconciliationDiscrepancy] = []
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT po.id, po.payment_id
                FROM payment_operations po
                LEFT JOIN payments p ON p.id = po.payment_id
                WHERE p.id IS NULL
                ORDER BY po.id
                """
            )
            for operation_id, payment_id in cursor.fetchall():
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        DiscrepancyKind.OPERATION_WITHOUT_PAYMENT,
                        str(operation_id),
                        f"payment {payment_id} is missing",
                    )
                )

            cursor.execute(
                """
                SELECT po.id, po.journal_transaction_id
                FROM payment_operations po
                LEFT JOIN ledger_transactions lt ON lt.id = po.journal_transaction_id
                WHERE lt.id IS NULL
                ORDER BY po.id
                """
            )
            for operation_id, journal_id in cursor.fetchall():
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        DiscrepancyKind.OPERATION_WITHOUT_JOURNAL,
                        str(operation_id),
                        f"journal {journal_id} is missing",
                    )
                )

            cursor.execute(
                """
                SELECT po.id
                FROM payment_operations po
                LEFT JOIN outbox_events oe
                    ON oe.aggregate_type = 'payment'
                   AND oe.aggregate_id = po.payment_id
                   AND oe.payload->>'operation_id' = po.id
                WHERE oe.id IS NULL
                ORDER BY po.id
                """
            )
            for (operation_id,) in cursor.fetchall():
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        DiscrepancyKind.OPERATION_WITHOUT_OUTBOX,
                        str(operation_id),
                        "transactional outbox event is missing",
                    )
                )

            cursor.execute(
                """
                SELECT oe.id, oe.payload->>'operation_id'
                FROM outbox_events oe
                LEFT JOIN payment_operations po ON po.id = oe.payload->>'operation_id'
                WHERE oe.aggregate_type = 'payment'
                  AND oe.payload ? 'operation_id'
                  AND po.id IS NULL
                ORDER BY oe.id
                """
            )
            for event_id, operation_id in cursor.fetchall():
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        DiscrepancyKind.OUTBOX_WITHOUT_OPERATION,
                        str(event_id),
                        f"operation {operation_id} is missing",
                    )
                )

            cursor.execute(
                """
                SELECT po.id, p.status, po.to_status
                FROM payment_operations po
                JOIN payments p ON p.id = po.payment_id
                WHERE p.status <> po.to_status
                ORDER BY po.id
                """
            )
            for operation_id, payment_status, expected_status in cursor.fetchall():
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        DiscrepancyKind.PAYMENT_STATUS_MISMATCH,
                        str(operation_id),
                        f"payment status {payment_status} != operation target {expected_status}",
                    )
                )

            cursor.execute(
                """
                SELECT lt.id,
                       COUNT(le.id) AS entry_count,
                       COALESCE(SUM(le.amount) FILTER (WHERE le.side = 'debit'), 0) AS debits,
                       COALESCE(SUM(le.amount) FILTER (WHERE le.side = 'credit'), 0) AS credits
                FROM ledger_transactions lt
                LEFT JOIN ledger_entries le ON le.transaction_id = lt.id
                GROUP BY lt.id
                ORDER BY lt.id
                """
            )
            for journal_id, entry_count, debits, credits in cursor.fetchall():
                if int(entry_count) < 2:
                    discrepancies.append(
                        ReconciliationDiscrepancy(
                            DiscrepancyKind.JOURNAL_ENTRY_COUNT_INVALID,
                            str(journal_id),
                            f"journal has {entry_count} entries",
                        )
                    )
                if int(debits) != int(credits):
                    discrepancies.append(
                        ReconciliationDiscrepancy(
                            DiscrepancyKind.JOURNAL_UNBALANCED,
                            str(journal_id),
                            f"debits={debits}, credits={credits}",
                        )
                    )

        discrepancies.sort(key=lambda item: (item.kind.value, item.entity_id, item.detail))
        return ReconciliationReport(tuple(discrepancies))


class PostgresReplayController:
    """Explicit replay controls for unpublished/poison outbox events only."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def reset_outbox_event(self, event_id: str) -> bool:
        if not event_id.strip():
            raise ValueError("event_id must not be empty")
        with psycopg.connect(self._dsn) as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_events
                SET attempts = 0, last_error = NULL
                WHERE id = %s AND published_at IS NULL
                RETURNING id
                """,
                (event_id,),
            )
            return cursor.fetchone() is not None
