import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg


@dataclass(frozen=True)
class OutboxEvent:
    id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, object]
    attempts: int


class PostgresOutbox:
    """Replay-safe PostgreSQL transactional outbox with expiring delivery leases.

    Delivery is at-least-once: publishing may happen more than once if a process
    crashes after external publication but before acknowledgement. Consumers must
    therefore deduplicate by event id.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self):
        return psycopg.connect(self._dsn)

    @staticmethod
    def _row_to_event(row: tuple[object, ...]) -> OutboxEvent:
        payload = row[4]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return OutboxEvent(
            id=str(row[0]),
            aggregate_type=str(row[1]),
            aggregate_id=str(row[2]),
            event_type=str(row[3]),
            payload=dict(payload),
            attempts=int(row[5]),
        )

    def claim_batch(
        self,
        *,
        batch_size: int = 50,
        max_attempts: int = 5,
        lease_seconds: int = 60,
    ) -> list[OutboxEvent]:
        """Claim available events and release crashed claims after a lease expires."""

        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, aggregate_type, aggregate_id, event_type, payload, attempts
                FROM outbox_events
                WHERE published_at IS NULL
                  AND attempts < %s
                  AND (
                    locked_at IS NULL
                    OR locked_at < NOW() - (%s * INTERVAL '1 second')
                  )
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (max_attempts, lease_seconds, batch_size),
            )
            events = [self._row_to_event(row) for row in cursor.fetchall()]
            if events:
                cursor.execute(
                    """
                    UPDATE outbox_events
                    SET locked_at = NOW()
                    WHERE id = ANY(%s)
                    """,
                    ([event.id for event in events],),
                )
            return events

    def acknowledge(self, event_id: str) -> bool:
        """Mark a claimed event as published after external delivery succeeds."""

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_events
                SET published_at = %s,
                    attempts = attempts + 1,
                    last_error = NULL,
                    locked_at = NULL
                WHERE id = %s AND published_at IS NULL
                RETURNING id
                """,
                (datetime.now(UTC), event_id),
            )
            return cursor.fetchone() is not None

    def record_failure(self, event_id: str, error: str) -> bool:
        """Record a failed delivery and release its lease for a later retry."""

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE outbox_events
                SET attempts = attempts + 1,
                    last_error = %s,
                    locked_at = NULL
                WHERE id = %s AND published_at IS NULL
                RETURNING id
                """,
                (error[:1000], event_id),
            )
            return cursor.fetchone() is not None

    def publish_batch(
        self,
        publish: Callable[[OutboxEvent], None],
        *,
        batch_size: int = 50,
        max_attempts: int = 5,
        lease_seconds: int = 60,
    ) -> int:
        """Claim events, publish outside the DB transaction, then acknowledge each one."""

        published = 0
        events = self.claim_batch(
            batch_size=batch_size,
            max_attempts=max_attempts,
            lease_seconds=lease_seconds,
        )

        for event in events:
            try:
                publish(event)
            except Exception as exc:  # noqa: BLE001 - broker adapters may raise arbitrary errors
                self.record_failure(event.id, str(exc))
                continue

            if self.acknowledge(event.id):
                published += 1

        return published

    def consume_once(
        self,
        *,
        consumer_name: str,
        event: OutboxEvent,
        handler: Callable[[OutboxEvent], None],
    ) -> bool:
        if not consumer_name.strip():
            raise ValueError("consumer_name must not be empty")

        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO consumed_events (consumer_name, event_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                RETURNING event_id
                """,
                (consumer_name, event.id),
            )
            claimed = cursor.fetchone()
            if claimed is None:
                return False
            handler(event)
        return True
