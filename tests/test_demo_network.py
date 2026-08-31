import os

from app.demo_network import run_demo
from app.operational_snapshot import DataState, SectionState


def test_demo_network_scenarios_feed_the_operator_snapshot() -> None:
    snapshot = run_demo(os.environ["DATABASE_URL"], reset=True)

    assert snapshot.data_state is DataState.FRESH
    assert snapshot.network.state is SectionState.AVAILABLE
    assert snapshot.network.observations == 4
    assert snapshot.network.by_disposition == {
        "accepted": 1,
        "late": 1,
        "timed_out": 1,
    }
    assert snapshot.network.timeouts == 1
    assert snapshot.network.late_responses == 1
    assert snapshot.network.p95_latency_ms is not None
    assert snapshot.network.p95_latency_ms > 0
    assert snapshot.missing_sections == []
