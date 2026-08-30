from datetime import UTC, datetime

from fastapi.testclient import TestClient

import app.main as main_module
from app.operational_snapshot import (
    DatabaseMeasurements,
    DataState,
    OperationalSnapshot,
    PostgresOperationalSnapshotReader,
    SectionState,
    SnapshotHealth,
    UnavailableOperationalSnapshotReader,
)
from app.reconciliation import (
    DiscrepancyKind,
    ReconciliationDiscrepancy,
    ReconciliationReport,
)


class StaticReconciler:
    def __init__(self, report: ReconciliationReport) -> None:
        self._report = report

    def inspect(self) -> ReconciliationReport:
        return self._report


class StaticSnapshotReader:
    def __init__(self, snapshot: OperationalSnapshot) -> None:
        self._snapshot = snapshot

    def read(self) -> OperationalSnapshot:
        return self._snapshot


def test_unavailable_reader_never_fabricates_zero_operational_metrics() -> None:
    snapshot = UnavailableOperationalSnapshotReader("database not configured").read()

    assert snapshot.data_state is DataState.PARTIAL
    assert snapshot.health is SnapshotHealth.DEGRADED
    assert snapshot.payments.state is SectionState.UNAVAILABLE
    assert snapshot.payments.total is None
    assert snapshot.ledger.balanced is None
    assert snapshot.outbox.unpublished is None
    assert snapshot.network.state is SectionState.UNAVAILABLE
    assert snapshot.missing_sections == ["payments", "ledger", "outbox", "network"]


def test_postgres_reader_classifies_reconciliation_and_poison_outbox_as_critical() -> None:
    reader = PostgresOperationalSnapshotReader("postgresql://unused")
    reader._measure_database = lambda: DatabaseMeasurements(  # type: ignore[method-assign]
        payment_total=7,
        payment_status_counts={"captured": 5, "pending": 2},
        operation_count=5,
        unpublished_outbox=3,
        poison_outbox=1,
        oldest_unpublished_age_seconds=42.5,
    )
    reader._reconciler = StaticReconciler(  # type: ignore[assignment]
        ReconciliationReport(
            (
                ReconciliationDiscrepancy(
                    DiscrepancyKind.JOURNAL_UNBALANCED,
                    "journal-1",
                    "debits=10, credits=8",
                ),
            )
        )
    )

    snapshot = reader.read()

    assert snapshot.health is SnapshotHealth.CRITICAL
    assert snapshot.payments.total == 7
    assert snapshot.payments.by_status == {"captured": 5, "pending": 2}
    assert snapshot.ledger.balanced is False
    assert snapshot.ledger.discrepancies == 1
    assert snapshot.ledger.discrepancy_kinds == {"journal_unbalanced": 1}
    assert snapshot.outbox.unpublished == 3
    assert snapshot.outbox.poison_messages == 1
    assert snapshot.network.state is SectionState.UNAVAILABLE
    assert snapshot.missing_sections == ["network"]
    assert len(snapshot.incidents) == 2


def test_postgres_reader_marks_plain_unpublished_backlog_degraded() -> None:
    reader = PostgresOperationalSnapshotReader("postgresql://unused")
    reader._measure_database = lambda: DatabaseMeasurements(  # type: ignore[method-assign]
        payment_total=1,
        payment_status_counts={"pending": 1},
        operation_count=0,
        unpublished_outbox=2,
        poison_outbox=0,
        oldest_unpublished_age_seconds=3.0,
    )
    reader._reconciler = StaticReconciler(ReconciliationReport(()))  # type: ignore[assignment]

    snapshot = reader.read()

    assert snapshot.health is SnapshotHealth.DEGRADED
    assert snapshot.ledger.balanced is True
    assert snapshot.incidents == []


def test_ops_endpoint_preserves_contract_and_unavailable_sections() -> None:
    snapshot = UnavailableOperationalSnapshotReader("test database unavailable").read()
    original = main_module.operational_snapshot_reader
    main_module.operational_snapshot_reader = StaticSnapshotReader(snapshot)
    client = TestClient(main_module.app)
    try:
        response = client.get("/v1/ops/snapshot")
    finally:
        main_module.operational_snapshot_reader = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["provenance"]["contract_version"] == "v1"
    assert payload["data_state"] == "partial"
    assert payload["payments"]["total"] is None
    assert payload["network"]["state"] == "unavailable"
    assert "network" in payload["missing_sections"]


def test_provenance_timestamp_is_timezone_aware() -> None:
    snapshot = UnavailableOperationalSnapshotReader("test").read()

    generated = snapshot.provenance.generated_at
    assert isinstance(generated, datetime)
    assert generated.tzinfo == UTC
