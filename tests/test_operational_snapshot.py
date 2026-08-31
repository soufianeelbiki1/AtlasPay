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


def measurements(**overrides: object) -> DatabaseMeasurements:
    values: dict[str, object] = {
        "payment_total": 1,
        "payment_status_counts": {"pending": 1},
        "operation_count": 0,
        "unpublished_outbox": 0,
        "poison_outbox": 0,
        "oldest_unpublished_age_seconds": 0.0,
        "network_observations": 4,
        "network_disposition_counts": {"accepted": 2, "late": 1, "timed_out": 1},
        "network_timeouts": 1,
        "network_late_responses": 1,
        "network_p95_latency_ms": 1800.0,
    }
    values.update(overrides)
    return DatabaseMeasurements(**values)  # type: ignore[arg-type]


def test_unavailable_reader_never_fabricates_zero_operational_metrics() -> None:
    snapshot = UnavailableOperationalSnapshotReader("database not configured").read()

    assert snapshot.data_state is DataState.PARTIAL
    assert snapshot.health is SnapshotHealth.DEGRADED
    assert snapshot.payments.state is SectionState.UNAVAILABLE
    assert snapshot.payments.total is None
    assert snapshot.ledger.balanced is None
    assert snapshot.outbox.unpublished is None
    assert snapshot.network.state is SectionState.UNAVAILABLE
    assert snapshot.network.observations is None
    assert snapshot.missing_sections == ["payments", "ledger", "outbox", "network"]


def test_postgres_reader_classifies_reconciliation_and_poison_outbox_as_critical() -> None:
    reader = PostgresOperationalSnapshotReader("postgresql://unused")
    reader._measure_database = lambda: measurements(  # type: ignore[method-assign]
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
    assert snapshot.data_state is DataState.FRESH
    assert snapshot.payments.total == 7
    assert snapshot.payments.by_status == {"captured": 5, "pending": 2}
    assert snapshot.ledger.balanced is False
    assert snapshot.ledger.discrepancies == 1
    assert snapshot.ledger.discrepancy_kinds == {"journal_unbalanced": 1}
    assert snapshot.outbox.unpublished == 3
    assert snapshot.outbox.poison_messages == 1
    assert snapshot.network.state is SectionState.AVAILABLE
    assert snapshot.network.observations == 4
    assert snapshot.network.timeouts == 1
    assert snapshot.network.late_responses == 1
    assert snapshot.network.p95_latency_ms == 1800.0
    assert snapshot.missing_sections == []
    assert len(snapshot.incidents) == 2


def test_postgres_reader_marks_plain_unpublished_backlog_degraded() -> None:
    reader = PostgresOperationalSnapshotReader("postgresql://unused")
    reader._measure_database = lambda: measurements(  # type: ignore[method-assign]
        unpublished_outbox=2,
        oldest_unpublished_age_seconds=3.0,
    )
    reader._reconciler = StaticReconciler(ReconciliationReport(()))  # type: ignore[assignment]

    snapshot = reader.read()

    assert snapshot.health is SnapshotHealth.DEGRADED
    assert snapshot.ledger.balanced is True
    assert snapshot.network.by_disposition == {"accepted": 2, "late": 1, "timed_out": 1}
    assert snapshot.incidents == []


def test_ops_endpoint_preserves_contract_and_unavailable_sections(monkeypatch) -> None:
    snapshot = UnavailableOperationalSnapshotReader("test database unavailable").read()
    original = main_module.operational_snapshot_reader
    main_module.operational_snapshot_reader = StaticSnapshotReader(snapshot)
    monkeypatch.setenv(main_module.OPS_TOKEN_ENV, "ops-test-token")
    client = TestClient(main_module.app)
    try:
        response = client.get(
            "/v1/ops/snapshot",
            headers={"Authorization": "Bearer ops-test-token"},
        )
    finally:
        main_module.operational_snapshot_reader = original

    assert response.status_code == 200
    payload = response.json()
    assert payload["provenance"]["contract_version"] == "v1"
    assert payload["data_state"] == "partial"
    assert payload["payments"]["total"] is None
    assert payload["network"]["state"] == "unavailable"
    assert "network" in payload["missing_sections"]


def test_ops_endpoint_is_disabled_without_configured_token(monkeypatch) -> None:
    monkeypatch.delenv(main_module.OPS_TOKEN_ENV, raising=False)
    response = TestClient(main_module.app).get("/v1/ops/snapshot")

    assert response.status_code == 503
    assert "disabled" in response.json()["detail"].lower()


def test_ops_endpoint_rejects_missing_and_invalid_bearer_credentials(monkeypatch) -> None:
    monkeypatch.setenv(main_module.OPS_TOKEN_ENV, "expected-secret")
    client = TestClient(main_module.app)

    missing = client.get("/v1/ops/snapshot")
    invalid = client.get(
        "/v1/ops/snapshot",
        headers={"Authorization": "Bearer wrong-secret"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.headers["www-authenticate"] == "Bearer"


def test_provenance_timestamp_is_timezone_aware() -> None:
    snapshot = UnavailableOperationalSnapshotReader("test").read()

    generated = snapshot.provenance.generated_at
    assert isinstance(generated, datetime)
    assert generated.tzinfo == UTC
