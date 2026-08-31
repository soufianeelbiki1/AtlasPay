"""Deterministic local network scenarios for the AtlasPay/Nexus demo."""

import argparse
import os
from dataclasses import dataclass

import psycopg

from app.canonical import AuthorizationRequest, CardPaymentInstrument, NetworkCorrelation
from app.iso8583 import ISO8583Codec, ISO8583Message
from app.network_coordinator import NetworkTransactionCoordinator
from app.network_flow import AuthorizationNetworkFlow
from app.network_history import PostgresNetworkObservationWriter
from app.network_routing import IssuerRoute, NetworkRouter, ReversalRegistry
from app.network_transport import ISO8583NetworkAdapter, TransportExchange, TransportOutcome
from app.operational_snapshot import OperationalSnapshot, PostgresOperationalSnapshotReader


@dataclass
class ScriptedTransport:
    exchange_result: TransportExchange

    def exchange(self, payload: bytes, *, timeout_seconds: float) -> TransportExchange:
        if not payload or timeout_seconds <= 0:
            raise ValueError("demo transport received invalid exchange arguments")
        return self.exchange_result


@dataclass
class StaticReversalCorrelations:
    value: NetworkCorrelation

    def next_for(
        self,
        *,
        original: NetworkCorrelation,
        route: IssuerRoute,
    ) -> NetworkCorrelation:
        if original == self.value:
            raise ValueError("demo reversal correlation must differ from original")
        return self.value


def _route() -> IssuerRoute:
    return IssuerRoute(
        name="issuer-a",
        acquirer_id="atlas-acquirer",
        issuer_id="issuer-bank-a",
        pan_prefix="411111",
        currencies=frozenset({"MAD"}),
    )


def _canonical(stan: str, rrn: str) -> AuthorizationRequest:
    return AuthorizationRequest(
        amount_minor=12_500,
        currency="MAD",
        merchant_id="DEMO-MERCHANT",
        terminal_id="TERM0001",
        instrument=CardPaymentInstrument(pan="4111111111111111"),
        correlation=NetworkCorrelation(stan=stan, rrn=rrn),
    )


def _request(stan: str, rrn: str) -> ISO8583Message:
    return ISO8583Message("0200", {3: "000000", 11: stan, 37: rrn})


def _response(stan: str, rrn: str) -> ISO8583Message:
    return ISO8583Message("0210", {11: stan, 37: rrn, 39: "00"})


def _flow(
    dsn: str,
    exchange_result: TransportExchange,
    reversal: NetworkCorrelation,
) -> AuthorizationNetworkFlow:
    return AuthorizationNetworkFlow(
        router=NetworkRouter((_route(),)),
        adapter=ISO8583NetworkAdapter(ScriptedTransport(exchange_result)),
        coordinator=NetworkTransactionCoordinator(),
        reversals=ReversalRegistry(),
        reversal_correlations=StaticReversalCorrelations(reversal),
        history=PostgresNetworkObservationWriter(dsn),
    )


def _reset_network_history(dsn: str) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute("DELETE FROM network_observations")


def run_demo(dsn: str, *, reset: bool = False) -> OperationalSnapshot:
    """Run accepted, timeout/late-response, and known-local-failure scenarios."""

    if reset:
        _reset_network_history(dsn)

    codec = ISO8583Codec()

    accepted_stan, accepted_rrn = "100001", "100000000001"
    accepted = _flow(
        dsn,
        TransportExchange(
            TransportOutcome.RESPONSE,
            response_payload=codec.encode(_response(accepted_stan, accepted_rrn)),
        ),
        NetworkCorrelation(stan="900001", rrn="900000000001"),
    )
    accepted_attempt = accepted.start(
        _canonical(accepted_stan, accepted_rrn),
        _request(accepted_stan, accepted_rrn),
        now=0.0,
        timeout_seconds=2.0,
    )
    accepted.exchange(accepted_attempt, completed_at=0.18)

    timeout_stan, timeout_rrn = "100002", "100000000002"
    timeout = _flow(
        dsn,
        TransportExchange(
            TransportOutcome.TIMEOUT,
            error="demo issuer response deadline exceeded",
            delivery_unknown=True,
        ),
        NetworkCorrelation(stan="900002", rrn="900000000002"),
    )
    timeout_attempt = timeout.start(
        _canonical(timeout_stan, timeout_rrn),
        _request(timeout_stan, timeout_rrn),
        now=1.0,
        timeout_seconds=2.0,
    )
    timeout.exchange(timeout_attempt, completed_at=3.0)
    timeout.handle_late_response(
        timeout_attempt,
        _response(timeout_stan, timeout_rrn),
        now=3.4,
    )

    failure_stan, failure_rrn = "100003", "100000000003"
    failure = _flow(
        dsn,
        TransportExchange(
            TransportOutcome.FAILURE,
            error="demo connection refused before write",
        ),
        NetworkCorrelation(stan="900003", rrn="900000000003"),
    )
    failure_attempt = failure.start(
        _canonical(failure_stan, failure_rrn),
        _request(failure_stan, failure_rrn),
        now=4.0,
        timeout_seconds=2.0,
    )
    failure.exchange(failure_attempt, completed_at=4.05)

    return PostgresOperationalSnapshotReader(dsn).read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic local network scenarios")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="clear existing network observations first (local demo databases only)",
    )
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL must point to a migrated local PostgreSQL database")
    snapshot = run_demo(dsn, reset=args.reset)
    print(snapshot.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
