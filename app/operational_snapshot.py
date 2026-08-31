"""Read-only operational snapshot contract for operator/control-plane consumers."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import psycopg
from pydantic import BaseModel, Field

from app.reconciliation import PostgresReconciler

CONTRACT_VERSION = "v1"
DEFAULT_OUTBOX_MAX_ATTEMPTS = 5


class SnapshotHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class DataState(StrEnum):
    FRESH = "fresh"
    PARTIAL = "partial"


class SectionState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class SnapshotProvenance(BaseModel):
    source: str = "atlaspay-api"
    generated_at: datetime
    contract_version: str = CONTRACT_VERSION


class PaymentSummary(BaseModel):
    state: SectionState
    total: int | None = Field(default=None, ge=0)
    by_status: dict[str, int] | None = None
    operations: int | None = Field(default=None, ge=0)
    reason: str | None = None


class LedgerSummary(BaseModel):
    state: SectionState
    balanced: bool | None = None
    discrepancies: int | None = Field(default=None, ge=0)
    discrepancy_kinds: dict[str, int] | None = None
    inspected_at: datetime | None = None
    reason: str | None = None


class OutboxSummary(BaseModel):
    state: SectionState
    unpublished: int | None = Field(default=None, ge=0)
    poison_messages: int | None = Field(default=None, ge=0)
    oldest_unpublished_age_seconds: float | None = Field(default=None, ge=0)
    reason: str | None = None


class NetworkSummary(BaseModel):
    state: SectionState
    observations: int | None = Field(default=None, ge=0)
    by_disposition: dict[str, int] | None = None
    timeouts: int | None = Field(default=None, ge=0)
    late_responses: int | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    reason: str | None = None


class OperationalSnapshot(BaseModel):
    provenance: SnapshotProvenance
    health: SnapshotHealth
    data_state: DataState
    payments: PaymentSummary
    ledger: LedgerSummary
    outbox: OutboxSummary
    network: NetworkSummary
    incidents: list[str]
    missing_sections: list[str]


class OperationalSnapshotReader(Protocol):
    def read(self) -> OperationalSnapshot: ...


@dataclass(frozen=True, slots=True)
class DatabaseMeasurements:
    payment_total: int
    payment_status_counts: dict[str, int]
    operation_count: int
    unpublished_outbox: int
    poison_outbox: int
    oldest_unpublished_age_seconds: float
    network_observations: int
    network_disposition_counts: dict[str, int]
    network_timeouts: int
    network_late_responses: int
    network_p95_latency_ms: float


class PostgresOperationalSnapshotReader:
    """Build a snapshot from durable state plus an on-demand read-only reconciliation."""

    def __init__(self, dsn: str, *, outbox_max_attempts: int = DEFAULT_OUTBOX_MAX_ATTEMPTS) -> None:
        if outbox_max_attempts <= 0:
            raise ValueError("outbox_max_attempts must be positive")
        self._dsn = dsn
        self._outbox_max_attempts = outbox_max_attempts
        self._reconciler = PostgresReconciler(dsn)

    def _connect(self):
        return psycopg.connect(self._dsn)

    def _measure_database(self) -> DatabaseMeasurements:
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute("SELECT status, COUNT(*) FROM payments GROUP BY status ORDER BY status")
            status_counts = {str(status): int(count) for status, count in cursor.fetchall()}
            payment_total = sum(status_counts.values())

            cursor.execute("SELECT COUNT(*) FROM payment_operations")
            operation_count = int(cursor.fetchone()[0])

            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE published_at IS NULL),
                    COUNT(*) FILTER (
                        WHERE published_at IS NULL AND attempts >= %s
                    ),
                    COALESCE(
                        EXTRACT(
                            EPOCH FROM (
                                NOW() - (
                                    MIN(created_at) FILTER (WHERE published_at IS NULL)
                                )
                            )
                        ),
                        0
                    )
                FROM outbox_events
                """,
                (self._outbox_max_attempts,),
            )
            unpublished, poison, oldest_age = cursor.fetchone()

            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(*) FILTER (WHERE transport_outcome = 'timeout'),
                    COUNT(*) FILTER (WHERE disposition = 'late'),
                    COALESCE(
                        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms),
                        0
                    )
                FROM network_observations
                """
            )
            network_total, network_timeouts, network_late, network_p95 = cursor.fetchone()

            cursor.execute(
                """
                SELECT disposition, COUNT(*)
                FROM network_observations
                WHERE disposition IS NOT NULL
                GROUP BY disposition
                ORDER BY disposition
                """
            )
            network_dispositions = {
                str(disposition): int(count) for disposition, count in cursor.fetchall()
            }

        return DatabaseMeasurements(
            payment_total=payment_total,
            payment_status_counts=status_counts,
            operation_count=operation_count,
            unpublished_outbox=int(unpublished),
            poison_outbox=int(poison),
            oldest_unpublished_age_seconds=max(float(oldest_age), 0.0),
            network_observations=int(network_total),
            network_disposition_counts=network_dispositions,
            network_timeouts=int(network_timeouts),
            network_late_responses=int(network_late),
            network_p95_latency_ms=max(float(network_p95), 0.0),
        )

    def read(self) -> OperationalSnapshot:
        generated_at = datetime.now(UTC)
        measurements = self._measure_database()
        reconciliation = self._reconciler.inspect()
        discrepancy_kinds = Counter(item.kind.value for item in reconciliation.discrepancies)
        incidents: list[str] = []

        if reconciliation.discrepancies:
            incidents.append(
                f"ledger/reconciliation has {len(reconciliation.discrepancies)} discrepancy(s)"
            )
        if measurements.poison_outbox:
            incidents.append(
                f"outbox has {measurements.poison_outbox} unpublished event(s) at retry limit"
            )

        health = SnapshotHealth.HEALTHY
        if reconciliation.discrepancies or measurements.poison_outbox:
            health = SnapshotHealth.CRITICAL
        elif measurements.unpublished_outbox:
            health = SnapshotHealth.DEGRADED

        return OperationalSnapshot(
            provenance=SnapshotProvenance(generated_at=generated_at),
            health=health,
            data_state=DataState.FRESH,
            payments=PaymentSummary(
                state=SectionState.AVAILABLE,
                total=measurements.payment_total,
                by_status=measurements.payment_status_counts,
                operations=measurements.operation_count,
            ),
            ledger=LedgerSummary(
                state=SectionState.AVAILABLE,
                balanced=reconciliation.clean,
                discrepancies=len(reconciliation.discrepancies),
                discrepancy_kinds=dict(sorted(discrepancy_kinds.items())),
                inspected_at=generated_at,
            ),
            outbox=OutboxSummary(
                state=SectionState.AVAILABLE,
                unpublished=measurements.unpublished_outbox,
                poison_messages=measurements.poison_outbox,
                oldest_unpublished_age_seconds=measurements.oldest_unpublished_age_seconds,
            ),
            network=NetworkSummary(
                state=SectionState.AVAILABLE,
                observations=measurements.network_observations,
                by_disposition=measurements.network_disposition_counts,
                timeouts=measurements.network_timeouts,
                late_responses=measurements.network_late_responses,
                p95_latency_ms=measurements.network_p95_latency_ms,
            ),
            incidents=incidents,
            missing_sections=[],
        )


class UnavailableOperationalSnapshotReader:
    """Explicit partial snapshot used when no durable database is configured."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def read(self) -> OperationalSnapshot:
        generated_at = datetime.now(UTC)
        unavailable = self._reason
        return OperationalSnapshot(
            provenance=SnapshotProvenance(generated_at=generated_at),
            health=SnapshotHealth.DEGRADED,
            data_state=DataState.PARTIAL,
            payments=PaymentSummary(state=SectionState.UNAVAILABLE, reason=unavailable),
            ledger=LedgerSummary(state=SectionState.UNAVAILABLE, reason=unavailable),
            outbox=OutboxSummary(state=SectionState.UNAVAILABLE, reason=unavailable),
            network=NetworkSummary(state=SectionState.UNAVAILABLE, reason=unavailable),
            incidents=["durable operational database is unavailable"],
            missing_sections=["payments", "ledger", "outbox", "network"],
        )
