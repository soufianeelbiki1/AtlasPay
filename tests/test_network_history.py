import os

import psycopg

from app.network_coordinator import TransactionDisposition
from app.network_history import NetworkObservation, PostgresNetworkObservationWriter
from app.network_routing import IssuerRoute, ReversalReason
from app.network_transport import TransportOutcome


def route() -> IssuerRoute:
    return IssuerRoute(
        name="issuer-a",
        acquirer_id="atlas-acquirer",
        issuer_id="issuer-bank-a",
        pan_prefix="411111",
        currencies=frozenset({"MAD"}),
    )


def test_network_observation_rejects_negative_latency() -> None:
    try:
        NetworkObservation(
            route=route(),
            transport_outcome=TransportOutcome.RESPONSE,
            disposition=TransactionDisposition.ACCEPTED,
            delivery_unknown=False,
            latency_ms=-1.0,
        )
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative latency must be rejected")


def test_postgres_writer_persists_operational_fields_without_card_identifiers() -> None:
    dsn = os.environ["DATABASE_URL"]
    writer = PostgresNetworkObservationWriter(dsn)

    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM network_observations")

    writer.record(
        NetworkObservation(
            route=route(),
            transport_outcome=TransportOutcome.TIMEOUT,
            disposition=TransactionDisposition.TIMED_OUT,
            delivery_unknown=True,
            latency_ms=1250.0,
            reversal_reason=ReversalReason.TIMEOUT,
        )
    )

    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT route_name, issuer_id, acquirer_id, transport_outcome,
                   disposition, delivery_unknown, latency_ms, reversal_reason
            FROM network_observations
            """
        )
        row = cursor.fetchone()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'network_observations'
            """
        )
        columns = {str(item[0]) for item in cursor.fetchall()}

    assert row == (
        "issuer-a",
        "issuer-bank-a",
        "atlas-acquirer",
        "timeout",
        "timed_out",
        True,
        1250.0,
        "timeout",
    )
    assert {"pan", "stan", "rrn", "de55", "payload"}.isdisjoint(columns)
