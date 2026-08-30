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
    """Replay-safe PostgreSQL transactional outbox helper.

    Delivery is at-least-once: publishing may happen more than once if a process crashes
    after external publication but before ``published_at`` is committed. Consumers must
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

    def publish_batch(
        self,
        publish: Callable[[OutboxEvent], None],
        *,
        batch_size: int = 50,
        max_attempts: int = 5,
    ) -> int:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")

        published = 0
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, aggregate_type, aggregate_id, event_type, payload, attempts
                FROM outbox_events
                WHERE published_at IS NULL AND attempts < %s
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (max_attempts, batch_size),
            )
            events = [self._row_to_event(row) for row in cursor.fetchall()]

            for event in events:
                try:
                    publish(event)
                except Exception as exc:  # noqa: BLE001 - broker adapters may raise arbitrary errors
                    cursor.execute(
                        """
                        UPDATE outbox_events
                        SET attempts = attempts + 1,
                            last_error = %s,
                            locked_at = NULL
                        WHERE id = %s
                        """,
                        (str(exc)[:1000], event.id),
                    )
                    continue

                cursor.execute(
                    """
                    UPDATE outbox_events
                    SET published_at = %s,
                        attempts = attempts + 1,
                        last_error = NULL,
                        locked_at = NULL
                    WHERE id = %s
                    """,
                    (datetime.now(UTC), event.id),
                )
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
